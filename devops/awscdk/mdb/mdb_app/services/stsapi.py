import aws_cdk
from aws_cdk import Duration

from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecr as ecr
#from datetime import date
from aws_cdk import aws_secretsmanager as secretsmanager

class stsapiService:
  def createService(self, config):

    ### STS API Service ###############################################################################################################
    service = "stsapi"

    # Set container configs
    if config.has_option(service, 'entry_point'):
        entry_point = ["/bin/sh", "-c", config[service]['entry_point']]
    else:
        entry_point = None

    bolt_port = config.getint('neo4j', 'bolt_port') 
    environment={
        "NEO4J_BOLT_URI":f"bolt://{self.NLB.load_balancer_dns_name}:{bolt_port}",
#        "NEO4J_MDB_URI":"bolt://{}:{}".format(self.NLB.load_balancer_dns_name, config.getint('neo4j', 'bolt_port)),
#        "NEO4J_MDB_USER":ecs.Secret.from_secrets_manager(self.secret, 'neo4j_user'),
#        "NEO4J_MDB_PASS":ecs.Secret.from_secrets_manager(self.secret, 'neo4j_password'),
    }

    secrets={
        "NEO4J_USER":ecs.Secret.from_secrets_manager(self.secret, 'neo4j_user'),
        "NEO4J_PASS":ecs.Secret.from_secrets_manager(self.secret, 'neo4j_password'),
#        "NEO4J_MDB_URI":ecs.Secret.from_secrets_manager(self.secret, 'neo4j_uri'),
    }


    taskDefinition = ecs.FargateTaskDefinition(self,
        "{}-{}-taskDef".format(self.namingPrefix, service),
        family=f"{config['main']['resource_prefix']}-{config['main']['tier']}-sts-api",
        cpu=config.getint(service, 'cpu'),
        memory_limit_mib=config.getint(service, 'memory')
    )

    ecr_repo = ecr.Repository.from_repository_arn(self, "{}_repo".format(service), repository_arn=config[service]['repo'])
    taskDefinition.add_container(
        service,
        #image=ecs.ContainerImage.from_registry("{}:{}".format(config[service]['repo'], config[service]['image'])),
        image=ecs.ContainerImage.from_ecr_repository(repository=ecr_repo, tag=config[service]['image']),
        cpu=config.getint(service, 'cpu'),
        memory_limit_mib=config.getint(service, 'memory'),
        port_mappings=[ecs.PortMapping(app_protocol=ecs.AppProtocol.http, container_port=config.getint(service, 'port'), name=service)],
        entry_point=entry_point,
        # secrets=secrets,
        environment=environment,
        logging=ecs.LogDrivers.aws_logs(
            stream_prefix="{}-{}".format(self.namingPrefix, service)
        )
    )

    ecsService = ecs.FargateService(self,
        "{}-{}-service".format(self.namingPrefix, service),
        service_name=f"{config['main']['resource_prefix']}-{config['main']['tier']}-sts-api",
        cluster=self.ECSCluster,
        task_definition=taskDefinition,
        enable_execute_command=True,
        min_healthy_percent=50,
        max_healthy_percent=200,
        circuit_breaker=ecs.DeploymentCircuitBreaker(
            enable=True,
            rollback=True
        )
    )


    ecsTarget = self.listener.add_targets("ECS-{}-Target".format(service),
        port=int(config[service]['port']),
        protocol=elbv2.ApplicationProtocol.HTTP,
        target_group_name=f"{config['main']['resource_prefix']}-{config['main']['tier']}-sts-api",
        health_check = elbv2.HealthCheck(
            path=config[service]['health_check_path'],
            timeout=Duration.seconds(config.getint(service, 'health_check_timeout')),
            interval=Duration.seconds(config.getint(service, 'health_check_interval')),),
        targets=[ecsService],)

    elbv2.ApplicationListenerRule(self, id="alb-{}-rule".format(service),
        conditions=[
            #elbv2.ListenerCondition.host_headers(config[service]['host'].split(',')),
            elbv2.ListenerCondition.path_patterns(config[service]['path'].split(','))
        ],
        priority=int(config[service]['priority_rule_number']),
        listener=self.listener,
        target_groups=[ecsTarget])
