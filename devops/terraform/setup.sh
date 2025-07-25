#!/bin/bash
if [ -f "/usr/bin/terraform" ]; then
        echo "Terraform is already installed"
else
        echo "Installing Terraform..." 
        sudo yum install -y yum-utils
        sudo yum-config-manager --add-repo https://rpm.releases.hashicorp.com/AmazonLinux/hashicorp.repo
        sudo yum install -y terraform
fi
alias tf=terraform
#
