import boto3
from configparser import ConfigParser
from constructs import Construct

from aws_cdk import Stack
from aws_cdk import RemovalPolicy
from aws_cdk import SecretValue
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_kms as kms
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_efs as efs
from aws_cdk import aws_certificatemanager as cfm
from aws_cdk import aws_s3 as s3
#from aws_cdk import Fn

from services import neo4j, stsapi

class Stack(Stack):
    def __init__(self, scope: Construct, **kwargs) -> None:
        super().__init__(scope, **kwargs)

        ### Read config
        config = ConfigParser()
        config.read('config.ini')
        
        self.namingPrefix = "{}-{}".format(config['main']['resource_prefix'], config['main']['tier'])

        ### Import VPC
        self.VPC = ec2.Vpc.from_lookup(self, "VPC",
            vpc_id = config['main']['vpc_id']
        )

        ### Secrets
#        self.secret = secretsmanager.Secret(self, "Secret",
#            secret_name="{}/{}".format(config['main']['resource_prefix'], config['main']['tier']),
#            secret_object_value={
#                "neo4j_user": SecretValue.unsafe_plain_text(config['db']['neo4j_user']),
#                "neo4j_password": SecretValue.unsafe_plain_text(config['db']['neo4j_password']),
#            }
#        )

        ### EFS - Neo4j
        EFSSecurityGroup = ec2.SecurityGroup(self, "EFSSecurityGroup", vpc=self.VPC, allow_all_outbound=True,)
        EFSSecurityGroup.add_ingress_rule(peer=ec2.Peer.ipv4(self.VPC.vpc_cidr_block),
            connection=ec2.Port.tcp(2049),
        )
        self.fileSystem = efs.FileSystem(self, "EfsFileSystem",
            vpc=self.VPC,
            encrypted=True,
            enable_automatic_backups=True,
            security_group=EFSSecurityGroup,
            removal_policy=RemovalPolicy.DESTROY
        )
        self.EFSAccessPoint = self.fileSystem.add_access_point("EFSAccessPoint",
            path="/{}".format(config['main']['tier']),
            create_acl=efs.Acl(
                owner_uid="7474",
                owner_gid="7474",
                permissions="755"
            ),
            posix_user=efs.PosixUser(
                uid="7474",
                gid="7474"
            )
        ) 

        ### ALB
        # Extract subnet IDs
        subnet1 = config.get('Subnets', 'subnet1')
        subnet2 = config.get('Subnets', 'subnet2')
        selected_subnets = ec2.SubnetSelection(
            subnets=[
                ec2.Subnet.from_subnet_id(self, "Subnet1", subnet1),
                ec2.Subnet.from_subnet_id(self, "Subnet2", subnet2)
            ]
        )

        self.ALB = elbv2.ApplicationLoadBalancer(self,
            "alb",
            load_balancer_name = f"{config['main']['resource_prefix']}-{config['main']['tier']}-alb",
            vpc=self.VPC,
            internet_facing=config.getboolean('alb', 'internet_facing'),
            vpc_subnets=selected_subnets
        )

        self.ALB.add_redirect(
            source_protocol=elbv2.ApplicationProtocol.HTTP,
            source_port=80,
            target_protocol=elbv2.ApplicationProtocol.HTTPS,
            target_port=443)

        # Get certificate ARN for specified domain name
        client = boto3.client('acm')
        response = client.list_certificates(
            CertificateStatuses=[
                'ISSUED',
            ],
        )

        for cert in response["CertificateSummaryList"]:
            if ('*.{}'.format(config['main']['domain']) in cert.values()):
                certARN = cert['CertificateArn']

        alb_cert = cfm.Certificate.from_certificate_arn(self, "alb-cert",
            certificate_arn=certARN)

        self.listener = self.ALB.add_listener("PublicListener",
            certificates=[
                alb_cert
            ],
            port=443)

        ### ALB Access log
        log_bucket = s3.Bucket.from_bucket_name(self, "AlbAccessLogsBucket", config['main']['alb_log_bucket_name'])
        log_prefix = f"{config['main']['program']}/{config['main']['tier']}/{config['main']['resource_prefix']}/alb-access-logs"

        self.ALB.log_access_logs(
            bucket=log_bucket,
            prefix=log_prefix
#            bucket=self.alb_logs_bucket,
#            prefix="alb-logs/"
        )

        ### ECS Cluster
        self.kmsKey = kms.Key(self, "ECSExecKey")

        self.ECSCluster = ecs.Cluster(self,
            "ecs",
            cluster_name = f"{config['main']['resource_prefix']}-{config['main']['tier']}-ecs",
            vpc=self.VPC,
            execute_command_configuration=ecs.ExecuteCommandConfiguration(
                kms_key=self.kmsKey
            ),
        )

        ### Fargate

        # Neo4j Service
        neo4j.neo4jService.createService(self, config)
    
        #neo4j_uri = "bolt://{}:{}".format(self.NLB.load_balancer_dns_name, config.getint('neo4j', 'bolt_port))"
        #nlb_dns_name = Fn.import_value("Neo4jNlbDnsNameExport")
        #bolt_port = config.getint('neo4j', 'bolt_port')
        #neo4j_uri = f"bolt://{nlb_dns_name}:{bolt_port}"

        ### Secrets
        self.secret = secretsmanager.Secret(self, "Secret",
            secret_name="{}/{}".format(config['main']['resource_prefix'], config['main']['tier']),
            secret_object_value={
                "neo4j_user": SecretValue.unsafe_plain_text(config['db']['neo4j_user']),
                "neo4j_pass": SecretValue.unsafe_plain_text(config['db']['neo4j_pass']),
                #"neo4j_uri": SecretValue.unsafe_plain_text(neo4j_uri)
            }
        )
        # API service
        stsapi.stsapiService.createService(self, config)

        # Add a fixed error message when browsing an invalid URL
        self.listener.add_action("ECS-Content-Not-Found",
            action=elbv2.ListenerAction.fixed_response(200,
                message_body="The requested resource is not available"))
