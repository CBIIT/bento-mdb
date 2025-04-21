# prefect-fnl

To use Terraform from cloudshell:

1. open cloudshell in the account you are provisioning
2. download and install terraform:

```
wget https://releases.hashicorp.com/terraform/1.3.6/terraform_1.3.6_linux_amd64.zip
unzip terraform_1.3.6_linux_amd64.zip
mkdir ~/bin
mv terraform ~/bin
```

3. clone your git repo:

```
git clone https://github.com/CBIIT/prefect-fnl.git
```

4. go to the repo folder and make sure you are on the correct branch:

```
cd prefect-fnl
git checkout main
cd terraform
```

5. create a workspace folder with the required tfvars and tfbackend files (this should be added to the backend S3 bucket for later reference once provisioning is done)
6. initialize your terraform workspace:

```
terraform init -reconfigure -backend-config=workspace/< PROJECT NAME >.tfbackend
terraform workspace new < WORKSPACE NAME >
terraform plan -var-file=workspace/< PROJECT NAME >.tfvars -out < PROJECT NAME >
```

7. once the plan is done and looks correct apply