import argparse
import sys

from .kernel_client import KernelClient
from .llm.deepseek import DeepSeekClient
from .loop import run_agent


def main():
    p = argparse.ArgumentParser(prog="agentos-run")
    p.add_argument("--task", required=True, help="The task for the agent.")
    p.add_argument("--session-id", required=True, help="Session id (由网关 StartSession 得到).")
    p.add_argument("--run-id", required=True, help="Run id (由网关分配).")
    p.add_argument("--socket", default="./agentos.sock", help="Kernel unix socket path.")
    p.add_argument("--max-steps", type=int, default=20)
    args = p.parse_args()

    kernel = KernelClient(args.socket)
    llm = DeepSeekClient()
    try:
        run_agent(args.task, llm, kernel,
                  session_id=args.session_id, run_id=args.run_id,
                  max_steps=args.max_steps)
        return 0  # 0 = 正常结束
    except Exception as exc:
        sys.stderr.write(f"runtime crashed: {exc}\n")
        return 1  # 非 0 = 崩溃/报错
    finally:
        kernel.close()


if __name__ == "__main__":
    sys.exit(main())
