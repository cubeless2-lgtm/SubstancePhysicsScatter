from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"plugin"))
from substance_physics_scatter.errors import APIException, HOST_ERRORS, optional_metadata, rollback_or_raise
from substance_physics_scatter.connections import incoming_sources
from substance_physics_scatter.bridge import FileQueue
import tempfile,json

class Prop:
    def __init__(self,name,category):self.name=name;self.category=category
    def getId(self):return self.name
    def getCategory(self):return self.category
class Node:
    def __init__(self,name,handle,props=()):self.name=name;self.mHandle=handle;self.props=list(props);self.links=[]
    def getIdentifier(self):return self.name
    def getProperties(self,category):return [p for p in self.props if p.category==category]
    def getPropertyFromId(self,name,category):return next((p for p in self.props if p.name==name and p.category==category),None)
    def getPropertyConnections(self,prop):return self.links
class Graph:
    def __init__(self,nodes):self.nodes={n.name:n for n in nodes}
    def getNodeFromId(self,name):return self.nodes.get(name)
class Connection:
    def __init__(self,a,b):self.a=a;self.b=b
    def getInputPropertyNode(self):return self.a[0]
    def getInputProperty(self):return self.a[1]
    def getOutputPropertyNode(self):return self.b[0]
    def getOutputProperty(self):return self.b[1]

class HostContracts(unittest.TestCase):
    def test_standard_and_reversed_endpoints(self):
        src=Prop("height",2);dst=Prop("inputNodeOutput",1)
        source=Node("same_id",10,[src]);sink=Node("sink",11,[dst]);graph=Graph([source,sink])
        # Endpoint wrappers have fresh opaque API handles even for the same logical node.
        wrapped_source=Node("same_id",987);wrapped_sink=Node("sink",654)
        for ends in (((wrapped_source,src),(wrapped_sink,dst)),((wrapped_sink,dst),(wrapped_source,src))):
            sink.links=[Connection(*ends)]
            a,p=incoming_sources(graph,"sink","inputNodeOutput")[0];self.assertIs(a,source);self.assertIs(p,src)
        other_source=Node("same_id",20,[src]);other_sink=Node("sink",21,[dst]);other=Graph([other_source,other_sink])
        other_sink.links=[Connection((Node("same_id",111),src),(Node("sink",222),dst))]
        self.assertIs(incoming_sources(other,"sink","inputNodeOutput")[0][0],other_source)
        self.assertIs(incoming_sources(graph,"sink","inputNodeOutput")[0][0],source)

    def test_connection_lookup_rejects_missing_or_invalid_categories(self):
        src=Prop("height",2);dst=Prop("inputNodeOutput",1)
        source=Node("source",10,[src]);sink=Node("sink",11,[dst]);graph=Graph([source,sink])
        self.assertEqual(incoming_sources(graph,"sink","inputNodeOutput"),[])
        with self.assertRaises(ValueError):incoming_sources(graph,"absent","inputNodeOutput")
        with self.assertRaises(ValueError):incoming_sources(graph,"sink","absent")
        cases=[Connection((source,Prop("height",1)),(sink,dst)),
               Connection((source,Prop("height",0)),(sink,dst)),
               Connection((source,src),(sink,Prop("wrong",1))),
               Connection((Node("absent",12),src),(sink,dst)),
               Connection((source,Prop("absent",2)),(sink,dst)),
               Connection((None,src),(sink,dst))]
        for connection in cases:
            sink.links=[connection]
            with self.assertRaises(ValueError):incoming_sources(graph,"sink","inputNodeOutput")
        sink.links=[Connection((source,src),(sink,dst))]*2
        with self.assertRaises(ValueError):incoming_sources(graph,"sink","inputNodeOutput")
        # Errors raised by the SDK lookup are not converted into an empty connection list.
        sink.getPropertyConnections=lambda prop:(_ for _ in ()).throw(APIException("SDK failure"))
        with self.assertRaises(APIException):incoming_sources(graph,"sink","inputNodeOutput")

    def test_sdk_baseexception_missing_only_and_bridge_response(self):
        def failure(code):
            error=APIException("SDK");error.mErrorCode=code;raise error
        self.assertIsNone(optional_metadata(lambda:failure(14),14))
        with self.assertRaises(APIException):optional_metadata(lambda:failure(99),14)
        with tempfile.TemporaryDirectory() as temp:
            queue=FileQueue(temp,lambda operation:failure(99))
            (queue.directory/"request.json").write_text('{"job_id":"sdk_error","operation":"inspect"}')
            queue.tick();response=json.loads((queue.responses/"sdk_error.json").read_text())
            self.assertEqual(response["status"],"error");self.assertIn("APIException",response["traceback"])
        self.assertFalse(isinstance(SystemExit(),HOST_ERRORS));self.assertFalse(isinstance(KeyboardInterrupt(),HOST_ERRORS))

    def test_rollback_error_keeps_both_causes(self):
        original=ValueError("original failure")
        def rollback():raise APIException("SDK restore failure")
        with self.assertRaises(RuntimeError) as context:rollback_or_raise(original,rollback)
        self.assertIn("original failure",str(context.exception));self.assertIn("SDK restore failure",str(context.exception));self.assertIs(context.exception.__cause__,original)

if __name__=="__main__":unittest.main(verbosity=2)
