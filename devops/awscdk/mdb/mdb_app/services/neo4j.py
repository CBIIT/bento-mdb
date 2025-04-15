import aws_cdk

from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ec2 as ec2
# from aws_cdk import aws_secretsmanager as secretsmanager

class neo4jService:
  def createService(self, config):

    ### Neo4j Service ###############################################################################################################
    service = "neo4j"

    # Set container configs
    if config.has_option(service, 'entry_point'):
        entry_point = ["/bin/sh", "-c", config[service]['entry_point']]
    else:
        entry_point = None

    environment={
        "NEO4J_AUTH":"{}/{}".format(config['db']['neo4j_user'], config['db']['neo4j_password']),
        "NEO4J_dbms_connector_bolt_advertised__address":"0.0.0.0",
        "NEO4J_dbms_connector_http_advertised__address":"0.0.0.0",
    }

    # secrets={
    # }

    dbVolume = ecs.Volume(
        name="neo4j-data",
        efs_volume_configuration=ecs.EfsVolumeConfiguration(
            file_system_id=self.fileSystem.file_system_id,
            authorization_config=ecs.AuthorizationConfig(
                access_point_id=self.EFSAccessPoint.access_point_id,
                iam="ENABLED"
            ),
            transit_encryption="ENABLED"
        )
    )

    taskDefinition = ecs.FargateTaskDefinition(self,
        "{}-{}-taskDef".format(self.namingPrefix, service),
        cpu=config.getint(service, 'cpu'),
        memory_limit_mib=config.getint(service, 'memory'),
        volumes=[dbVolume]
    )

    dbContainer = taskDefinition.add_container(
        service,
        image=ecs.ContainerImage.from_registry(config[service]['image']),
        cpu=config.getint(service, 'cpu'),
        memory_limit_mib=config.getint(service, 'memory'),
        port_mappings=[ecs.PortMapping(container_port=config.getint(service, 'port'), name=service)],
        # user="root",
        entry_point=entry_point,
        # secrets=secrets,
        environment=environment,
        logging=ecs.LogDrivers.aws_logs(
            stream_prefix="{}-{}".format(self.namingPrefix, service)
        )
    )
    containerVolumeMountPoint = ecs.MountPoint(
        read_only=False,
        container_path="{}".format(config[service]['data_directory']),
        source_volume=dbVolume.name
    )
    dbContainer.add_mount_points(containerVolumeMountPoint)
    self.fileSystem.grant_root_access(taskDefinition.task_role)

    ecsService = ecs.FargateService(self,
        "{}-{}-service".format(self.namingPrefix, service),
        cluster=self.ECSCluster,
        task_definition=taskDefinition,
        enable_execute_command=True,
        min_healthy_percent=0,
        max_healthy_percent=100,
        circuit_breaker=ecs.DeploymentCircuitBreaker(
            enable=True,
            rollback=True
        )
    )

    ### NLB - Neo4j ###############################################################################################################
    if config.getboolean('nlb', 'internet_facing'):
        subnets=ec2.SubnetSelection(
            subnets=self.VPC.select_subnets(one_per_az=True,subnet_type=ec2.SubnetType.PUBLIC).subnets
        )
    else:
        subnets=ec2.SubnetSelection(
            subnets=self.VPC.select_subnets(one_per_az=True,subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS).subnets
        )

    self.NLB = elbv2.NetworkLoadBalancer(self,
        "nlb",
        vpc=self.VPC,
        internet_facing=config.getboolean('nlb', 'internet_facing'),
        vpc_subnets=subnets,
    )
    NLBSecurityGroup = ec2.SecurityGroup(self, "NLBSecurityGroup", vpc=self.VPC, allow_all_outbound=True,)
    NLBSecurityGroup.add_ingress_rule(peer=ec2.Peer.any_ipv4(),
        connection=ec2.Port.tcp(config.getint(service, 'port')),
    )
    self.NLB.add_security_group(NLBSecurityGroup)
    ecsService.connections.security_groups[0].add_ingress_rule(
        NLBSecurityGroup,
        ec2.Port.tcp(config.getint(service, 'port'))
    )

    nlbTargetGroup = elbv2.NetworkTargetGroup(self,
        id="nlbTargetGroup",
        target_type=elbv2.TargetType.IP,
        protocol=elbv2.Protocol.TCP,
        port=config.getint(service, 'port'),
        vpc=self.VPC
    )
    # nlbTargetGroup.configure_health_check(
    #    interval=aws_cdk.Duration.seconds(60),
    #    timeout=aws_cdk.Duration.seconds(45),
    # )
    nlbListener = self.NLB.add_listener("Listener", port=config.getint(service, 'port'),)
    nlbListener.add_target_groups("target", nlbTargetGroup)
    nlbTargetGroup.add_target(ecsService)