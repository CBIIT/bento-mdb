import aws_cdk as cdk
import jsii
from constructs import Construct, IConstruct
from configparser import ConfigParser
from aws_cdk import aws_iam as iam

@jsii.implements(cdk.IAspect)
class MyAspect:
    def visit(self, node):

        # Read config file
        config = ConfigParser()
        config.read('config.ini')

        if isinstance(node, iam.CfnRole):
            if config.has_option('iam', 'role_prefix'):
                resolvedLogicalId = cdk.Stack.of(node).resolve(node.logical_id)
                #roleName = config['iam']['role_prefix'] + '-' + resolvedLogicalId
                roleName = config['iam']['role_prefix'] + '-' + config['main']['tier'] + '-' + resolvedLogicalId
                roleName = roleName[:64]  # Ensure the role name is within the 64 character limit
                node.role_name = roleName
