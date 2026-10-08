import json
import sys


def ingress_name(service):
    if service is None:
        return "mcp"
    containers = service.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    ingress = [container for container in containers if container.get("ports")]
    if len(ingress) != 1:
        raise ValueError("Cloud Run service must have exactly one ingress container")
    return ingress[0].get("name") or "__default__"


def configure_mcp_service(service, mcp_image, searxng_image):
    service = json.loads(json.dumps(service))
    mcp = next(c for c in service["spec"]["template"]["spec"]["containers"] if c.get("ports"))
    mcp.update(name="mcp", image=mcp_image, ports=[{"containerPort": 8000}], command=["uvicorn"],
               args=["mcp_server.server:app", "--host", "0.0.0.0", "--port", "8000"],
               resources={"limits": {"cpu": "1", "memory": "512Mi"}})

    env = {item["name"]: item for item in mcp.get("env", [])}
    env.update({n: {"name": n, "value": v} for n, v in {"ENVIRONMENT": "production", "SEARXNG_BASE_URL": "http://localhost:8080"}.items()})
    env.update({n: {"name": n, "valueFrom": {"secretKeyRef": {"name": n, "key": "latest"}}} for n in ("OPENROUTER_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "DATABASE_URL", "SESSION_SECRET")})
    mcp["env"] = list(env.values())

    annotations = service["spec"]["template"].setdefault("metadata", {}).setdefault("annotations", {})
    annotations["run.googleapis.com/container-dependencies"] = '{"mcp":["searxng"]}'
    searxng = {"name": "searxng", "image": searxng_image, "resources": {"limits": {"cpu": "1", "memory": "512Mi"}},
               "env": [{"name": "SEARXNG_SECRET", "valueFrom": {"secretKeyRef": {"name": "SEARXNG_SECRET", "key": "latest"}}}],
               "startupProbe": {"tcpSocket": {"port": 8080}, "periodSeconds": 2, "timeoutSeconds": 2, "failureThreshold": 30}}
    service["spec"]["template"]["spec"]["containers"] = [mcp, searxng]
    service.pop("status", None)
    metadata = service.get("metadata", {})
    for key in ("resourceVersion", "uid", "generation", "creationTimestamp", "deletionTimestamp", "managedFields", "selfLink"):
        metadata.pop(key, None)
    return service


def main():
    args = sys.argv[1:]
    if not args:
        print("mcp")
        return
    if args[0] == "configure":
        with open(args[1], encoding="utf-8") as service_file:
            configured = configure_mcp_service(json.load(service_file), args[2], args[3])
        print(json.dumps(configured))
        return
    with open(args[0], encoding="utf-8") as service_file:
        service = json.load(service_file)
    try:
        print(ingress_name(service))
    except ValueError as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()
