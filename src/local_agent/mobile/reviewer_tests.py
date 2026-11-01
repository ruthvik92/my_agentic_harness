"""Validate reviewer-selected tests against captured executions before clean replay."""

from local_agent.workspace.options import check_directory, validate_options


def selected_tests(store, project, declarations, observations):
    if not isinstance(declarations, list) or not 1 <= len(declarations) <= 8:
        raise ValueError("Reviewer must select and execute between one and eight test commands")
    commands = []
    for item in declarations:
        if not isinstance(item, dict) or set(item) != {"argv", "cwd"}:
            raise ValueError("Reviewer tests require argv and cwd")
        argv, cwd = item["argv"], item["cwd"]
        if (
            not isinstance(argv, list) or not 1 <= len(argv) <= 128
            or any(not isinstance(arg, str) or not arg or "\x00" in arg or len(arg) > 4096
                   for arg in argv)
        ):
            raise ValueError("Invalid reviewer test arguments")
        if not isinstance(cwd, str) or (cwd != "project" and not cwd.startswith("project/")):
            raise ValueError("Reviewer tests must run within project")
        directory = "." if cwd == "project" else cwd[len("project/"):]
        directory = validate_options({"working_directory": directory})["working_directory"]
        check_directory(project, directory)
        executed = False
        for observation in observations:
            if (observation["tool"] != "run_command"
                    or observation["status"] != "succeeded" or observation["exit_code"] != 0):
                continue
            # Display previews truncate argv; matching always uses the original tool arguments.
            args = store.blobs.json(observation["arguments_ref"])
            if args.get("argv") == argv and args.get("cwd", "project") == cwd:
                executed = True
                break
        if not executed:
            raise ValueError("Selected test has no successful captured execution: " + repr(argv))
        command = {"argv": argv, "cwd": directory}
        if command not in commands:
            commands.append(command)
    return commands
