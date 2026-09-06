# Deploying to AWS (ECR + EC2 self-hosted runner)

Region used throughout: `ap-south-1` (Mumbai). Substitute your own if different.
Account ID is written as `<ACCOUNT_ID>` — get yours with `aws sts get-caller-identity`.

Order matters. Do not skip step 0.

---

## 0. Verify locally first

Never debug a Dockerfile on a remote host.

```bash
docker build --build-arg GIT_SHA=$(git rev-parse --short HEAD) -t phishing-detection:local .
docker run -d --name pd -p 8080:8080 -e TRAIN_API_KEY=localsecret phishing-detection:local

curl -s localhost:8080/health
# {"status":"ok","model_loaded":false,"training":"idle"}

curl -X POST -H "X-API-Key: localsecret" localhost:8080/train
curl -s localhost:8080/train/status        # poll until "succeeded" (~2 min)
curl -s localhost:8080/health              # model_loaded should now be true

docker rm -f pd
```

`model_loaded: false` on a fresh container is expected — `final_model/` is gitignored, so the
image ships without a model and you train once after deploy.

---

## 1. Create the ECR repository

```bash
aws ecr create-repository \
  --repository-name networksecurity \
  --region ap-south-1 \
  --image-scanning-configuration scanOnPush=true
```

Note the `repositoryUri` it prints. It looks like
`<ACCOUNT_ID>.dkr.ecr.ap-south-1.amazonaws.com/networksecurity`.

Add a lifecycle policy so untagged layers do not accumulate charges:

```bash
aws ecr put-lifecycle-policy \
  --repository-name networksecurity \
  --region ap-south-1 \
  --lifecycle-policy-text '{
    "rules": [{
      "rulePriority": 1,
      "description": "expire untagged images after 7 days",
      "selection": {"tagStatus":"untagged","countType":"sinceImagePushed","countUnit":"days","countNumber":7},
      "action": {"type":"expire"}
    }]
  }'
```

---

## 2. IAM policy for the CI user

Do not attach `AdministratorAccess`. Create this policy and attach it to the IAM user whose
access keys go into GitHub secrets. Save as `ci-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EcrAuth",
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    },
    {
      "Sid": "EcrPushPull",
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:CompleteLayerUpload",
        "ecr:GetDownloadUrlForLayer",
        "ecr:InitiateLayerUpload",
        "ecr:PutImage",
        "ecr:UploadLayerPart",
        "ecr:BatchGetImage"
      ],
      "Resource": "arn:aws:ecr:ap-south-1:<ACCOUNT_ID>:repository/networksecurity"
    }
  ]
}
```

```bash
aws iam create-policy --policy-name PhishingCIPolicy --policy-document file://ci-policy.json
aws iam attach-user-policy --user-name <your-ci-user> \
  --policy-arn arn:aws:iam::<ACCOUNT_ID>:policy/PhishingCIPolicy
```

If you also want the training pipeline to sync artifacts to S3, add a second statement for
`s3:PutObject`, `s3:GetObject`, `s3:ListBucket` scoped to that one bucket.

---

## 3. Launch the EC2 instance

**Instance type matters.** `t2.micro` has 1 GB of RAM. GridSearchCV over five classifiers with
`n_jobs=-1` will be OOM-killed on it, and the failure looks like the container silently dying.
Use `t3.small` (2 GB) at minimum. `t3.medium` if you want headroom.

- AMI: Ubuntu Server 24.04 LTS
- Type: `t3.small`
- Storage: 20 GB gp3 (Docker images plus artifacts fill 8 GB fast)
- Key pair: create one and keep the `.pem`
- Security group: see step 4

Then add swap, which is what keeps a 2 GB box from dying during training:

```bash
ssh -i key.pem ubuntu@<EC2_PUBLIC_IP>

sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## 4. Security group

Three rules, no more:

| Type       | Port | Source              | Why |
| ---------- | ---- | ------------------- | --- |
| SSH        | 22   | **your IP only**    | admin |
| Custom TCP | 8080 | 0.0.0.0/0           | the API |
| —          | —    | outbound all        | ECR pulls, GitHub runner |

Do not open 22 to `0.0.0.0/0`. If your home IP changes, update the rule; do not widen it.

Port 8080 open to the world is acceptable for a demo, but `/train` is protected by
`TRAIN_API_KEY` for exactly this reason. Set that secret.

---

## 5. Install Docker on the instance

```bash
sudo apt-get update && sudo apt-get upgrade -y

curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

sudo usermod -aG docker ubuntu
newgrp docker            # or log out and back in

docker --version
```

---

## 6. Register the GitHub self-hosted runner

In the GitHub repo: **Settings → Actions → Runners → New self-hosted runner → Linux x64**.
GitHub shows a token that expires in one hour; copy the exact commands it gives you. They look
like this:

```bash
mkdir actions-runner && cd actions-runner
curl -o actions-runner-linux-x64.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.xxx.x/actions-runner-linux-x64-2.xxx.x.tar.gz
tar xzf actions-runner-linux-x64.tar.gz

./config.sh --url https://github.com/prabhatcodes/Phishing-Detection-MLOps --token <TOKEN>
```

When `config.sh` asks for the runner label, press Enter to accept `self-hosted`. The workflow's
`runs-on: self-hosted` matches that label.

Install it as a service so it survives reboots and SSH disconnects. Running `./run.sh` in a
terminal is the most common reason a deploy "randomly stops working":

```bash
sudo ./svc.sh install
sudo ./svc.sh start
sudo ./svc.sh status
```

The runner should now show as **Idle** in the GitHub Runners page.

---

## 7. GitHub secrets

**Settings → Secrets and variables → Actions → New repository secret.**

Required:

| Secret | Value |
| ------ | ----- |
| `AWS_ACCESS_KEY_ID` | from your CI IAM user |
| `AWS_SECRET_ACCESS_KEY` | from your CI IAM user |
| `AWS_REGION` | `ap-south-1` |
| `ECR_REPOSITORY_NAME` | `networksecurity` |

Optional, but set `TRAIN_API_KEY` before the instance is publicly reachable:

| Secret | Value |
| ------ | ----- |
| `TRAIN_API_KEY` | any long random string (`openssl rand -hex 24`) |
| `TRAINING_BUCKET_NAME` | S3 bucket for artifact sync, or leave unset |
| `MONGODB_URL_KEY` | Atlas connection string, or leave unset |
| `MLFLOW_TRACKING_URI` / `_USERNAME` / `_PASSWORD` | DagsHub, or leave unset |

Unset optional secrets resolve to empty strings, which the app treats as "feature disabled".
That is deliberate: the deployment works with only the four required secrets.

---

## 8. First deploy

```bash
git push origin main
```

Watch the Actions tab. Three jobs run in order:

1. **ci** — ruff and pytest on a GitHub-hosted runner. A failure here stops everything.
2. **build-and-push** — builds the image, pushes `:latest` and `:<sha>` to ECR.
3. **deploy** — runs on your EC2 box: pulls the SHA tag, removes the old container, starts the
   new one, polls `/health` up to 20 times before declaring success.

Then train once, because the image ships without a model:

```bash
curl -X POST -H "X-API-Key: <TRAIN_API_KEY>" http://<EC2_PUBLIC_IP>:8080/train
curl http://<EC2_PUBLIC_IP>:8080/train/status
```

The model is written to the `networksecurity-model` Docker volume, mounted at
`/app/final_model`, so it survives the next deploy. Without that volume you would have to
retrain after every push.

Open `http://<EC2_PUBLIC_IP>:8080/docs` to demo.

---

## 9. Rollback

The SHA tag is the point of tagging images with the SHA.

```bash
# on the EC2 instance
aws ecr describe-images --repository-name networksecurity --region ap-south-1 \
  --query 'sort_by(imageDetails,&imagePushedAt)[-5:].[imageTags[0],imagePushedAt]' --output table

REG=<ACCOUNT_ID>.dkr.ecr.ap-south-1.amazonaws.com
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin $REG

docker rm -f networksecurity
docker run -d --name networksecurity --restart unless-stopped -p 8080:8080 \
  -v networksecurity-model:/app/final_model \
  -e TRAIN_API_KEY=<key> \
  $REG/networksecurity:<GOOD_SHA>
```

---

## 10. Troubleshooting

**Deploy job never starts.** The runner is offline. `sudo ./svc.sh status` on the instance.

**`no basic auth credentials` on pull.** The ECR login token lasts 12 hours. The workflow logs
in each run; if you are pulling manually, re-run `aws ecr get-login-password | docker login`.

**Health check fails, container exits immediately.** `docker logs networksecurity`. Most often a
missing dependency after a requirements change, or the port not matching.

**Container is killed during `/train`.** Out of memory. Check `dmesg | tail`. Add swap (step 3)
or move to `t3.medium`.

**`permission denied` on the Docker socket.** The `usermod -aG docker` did not take effect for
the runner service. `sudo systemctl restart actions.runner.*`.

**Everything green but the URL times out.** Security group is missing the 8080 inbound rule, or
you are using the private IP.

---

## 11. Cost and teardown

`t3.small` in ap-south-1 is roughly $15/month if left running, plus about $0.10/GB-month for
ECR storage and 20 GB of EBS at about $1.60/month. Set a billing alarm before you start:

```bash
aws budgets create-budget --account-id <ACCOUNT_ID> \
  --budget '{"BudgetName":"monthly","BudgetLimit":{"Amount":"10","Unit":"USD"},"TimeUnit":"MONTHLY","BudgetType":"COST"}'
```

Stop the instance between demos (`aws ec2 stop-instances --instance-ids <id>`) — you keep the
EBS volume and the runner reconnects on start, and you stop paying for compute. Note the public
IP changes on restart unless you attach an Elastic IP.

To tear everything down:

```bash
aws ec2 terminate-instances --instance-ids <id>
aws ecr delete-repository --repository-name networksecurity --force --region ap-south-1
```

Remove the runner from GitHub's Runners page too, otherwise it lingers as offline.

---

## Next step up

This deployment is one container on one instance, replaced in place. The honest limitation is
that the replace step drops requests for a few seconds and there is no autoscaling. Moving to
ECS Fargate behind an ALB gives rolling deploys, health-check-gated rollback, and no host to
patch. The Dockerfile does not change; the workflow's `deploy` job is replaced by a task
definition update. That is the natural next iteration, not Kubernetes.
