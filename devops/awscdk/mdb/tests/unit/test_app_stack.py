import aws_cdk as core
import aws_cdk.assertions as assertions

from mdb_app.stack import Stack

# example tests. To run these tests, uncomment this file along with the example
# resource in app/app_stack.py
# def test_sqs_queue_created():
#     app = core.App()
#     stack = AppStack(app, "app")
#     template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
