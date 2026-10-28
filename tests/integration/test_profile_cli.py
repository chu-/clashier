from tests.conftest import GROUP, NODE_A, NODE_B
from tests.support import read_yaml_document, write_yaml_document


def test_activation_observes_real_controller_without_switching_nodes(json_run, config_dir, local_core):
    controller = local_core()
    core_path = config_dir / "clash-verge.yaml"
    core = read_yaml_document(core_path)
    core["external-controller"] = controller.address
    write_yaml_document(core_path, core)
    write_yaml_document(config_dir / "profiles/p2.yaml", {
        "proxies": [{"name": name, "type": "vless"} for name in (NODE_A, NODE_B)],
        "proxy-groups": [{"name": GROUP, "type": "select", "proxies": [NODE_A, NODE_B, "DIRECT"]}],
    })
    result, value = json_run("profile", "activate", "--core-only", "p2")
    assert result.exit_code == 0
    assert value["data"]["verification"]["status"] == "matched"
    assert value["data"]["verification"]["profile_identity"] == "not_exposed"
    assert value["context"]["profile_uid"] == "p2"
    assert controller.selected == NODE_A
    assert controller.writes == []
    assert len(controller.reloads) == 1
