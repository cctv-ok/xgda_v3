"""CSV 结果导出"""
import os
import pandas as pd


def write_result_csv(out_path: str, param: dict, score: float,
                     res: dict, mode: str = "grid", tag: str = "train") -> None:
    """追加一行结果到 CSV。文件不存在时写表头，存在则追加。"""
    row = {
        "run_mode": mode,
        "dataset": tag,
        "z_min": param.get("z_min"),
        "z_max": param.get("z_max"),
        "score": score,
        "sharpe": res["sharpe"],
        "win_rate": res["win_rate"],
        "max_drawdown": res["max_drawdown"],
        "calmar": res["calmar"],
        "total_closed": res["total_closed"],
        "final_value": res["final_value"],
    }
    df_out = pd.DataFrame([row])
    if os.path.exists(out_path):
        df_out.to_csv(out_path, mode="a", header=False,
                      index=False, encoding="utf-8-sig")
    else:
        df_out.to_csv(out_path, mode="w", header=True,
                      index=False, encoding="utf-8-sig")
