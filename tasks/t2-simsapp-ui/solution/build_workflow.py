"""Build the reference native n8n graph; the current acceptance profile rejects If."""

import json
from pathlib import Path


def build() -> dict:
    root = Path(__file__).resolve().parent
    source = (root / "reference.js").read_text()

    def node(name, kind, version, parameters, x):
        return {
            "id": name,
            "name": name,
            "type": "n8n-nodes-base." + kind,
            "typeVersion": version,
            "parameters": parameters,
            "position": [x, 0],
        }

    def assignment(name, value, kind="string"):
        return {"id": name, "name": name, "type": kind, "value": value}

    def set_node(name, fields, x):
        return node(
            name, "set", 3.4, {"assignments": {"assignments": fields}, "options": {}}, x
        )

    nodes = [
        node("Start", "manualTrigger", 1, {}, 0),
        set_node(
            "BenchInput",
            [assignment("bench", '{"input":{},"tools":{}}', "object")],
            200,
        ),
        node(
            "Decide",
            "code",
            2,
            {
                "mode": "runOnceForAllItems",
                "language": "javaScript",
                "jsCode": source
                + '\nconst incoming = $input.first().json;\nconst state = incoming.bench ? {input: incoming.bench.input} : $("Decide").last().json;\nreturn [{json: step(state, incoming.bench ? null : incoming)}];',
            },
            400,
        ),
        node(
            "Finished",
            "if",
            2.2,
            {
                "conditions": {
                    "options": {
                        "caseSensitive": True,
                        "leftValue": "",
                        "typeValidation": "strict",
                        "version": 2,
                    },
                    "conditions": [
                        {
                            "id": "done",
                            "leftValue": "={{$json.done}}",
                            "rightValue": True,
                            "operator": {
                                "type": "boolean",
                                "operation": "true",
                                "singleValue": True,
                            },
                        }
                    ],
                    "combinator": "and",
                },
                "options": {},
            },
            600,
        ),
        node(
            "UI request",
            "httpRequest",
            4.2,
            {
                "method": "POST",
                "url": "={{$('BenchInput').first().json.bench.tools.base_url + '/tools/' + $json.operation}}",
                "sendHeaders": True,
                "headerParameters": {
                    "parameters": [
                        {
                            "name": "Authorization",
                            "value": "={{'Bearer ' + $('BenchInput').first().json.bench.tools.capability}}",
                        }
                    ]
                },
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{JSON.stringify({schema_version:'1.0',arguments:$json.arguments})}}",
                "options": {
                    "timeout": 5000,
                    "response": {"response": {"responseFormat": "json"}},
                },
            },
            800,
        ),
        set_node(
            "BenchResult",
            [
                assignment("status", "={{$json.claim.status}}"),
                assignment("reason_code", "={{$json.claim.reason_code}}"),
                assignment("result", "={{$json.claim.result}}", "object"),
            ],
            1000,
        ),
    ]

    def edge(name):
        return {"node": name, "type": "main", "index": 0}

    connections = {
        a: {"main": [[edge(b)]]}
        for a, b in [
            ("Start", "BenchInput"),
            ("BenchInput", "Decide"),
            ("Decide", "Finished"),
            ("UI request", "Decide"),
        ]
    }
    connections["Finished"] = {"main": [[edge("BenchResult")], [edge("UI request")]]}
    return {
        "id": "wb19Reference001",
        "name": "T2 context-aware UI reference",
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
    }


if __name__ == "__main__":
    Path(__file__).with_name("workflow.json").write_text(
        json.dumps(build(), indent=2) + "\n"
    )
