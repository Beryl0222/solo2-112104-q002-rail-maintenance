# 多语种铁路检修记录与设备限制联动

本项目整理铁路检修控制室从承包商交班文本、调度通告和现场复核记录接收故障描述。设备昵称与线路正式编号经常混用，临时限速的解除条件也可能晚于维修完成记录；把文本分类结果直接当成设备恢复会让调度人员基于过时限制安排运行。

本仓库提供一套可持续使用的 Python（3.11 标准库）文本整理与检修状态查询能力：值班人员从原始叙述中找到相关设备和事件，并据此判断哪些事项仍影响调度。

## 核心规则（系统强制，不可绕过）

- **“更换”“检查完成”“修好了”是不同事实**，分别成事件，互不代表。
- **调度限制只能由调度通告开启和解除**。承包商交班或现场复核中的
  “修好了”“可以申请恢复常速”等表述一律记为“无授权表述”，仅提示，
  不会被转成运行许可；“待复核合格后另行解除”等条件式表述不产生事件。
- **别名映射经确认后才生效，可修订**；修订只影响之后入库的文本，
  已入库事件保留当时解析到的对象与映射版本。
- **归属纠错走“提议 → 确认”流程**；事件的原始入库归属永远保留，
  修订链可随时回看。
- 状态按事件**发生时间**归算，与材料到达顺序无关：晚到的补充记录、
  现场复核和通告会自然并入既有时间线。

## 快速开始

```bash
python3 -m mcs init --data-dir mcs_state                 # 初始化（含种子实体与别名）
python3 -m mcs ingest data/shift_handover.jsonl          # 导入合成演练记录
python3 -m mcs pending                                   # 按线路查看当前待处理事项
python3 -m mcs pending --line SEC-K17                    # 按线路/设备过滤
python3 -m mcs restrictions --entity SEC-K17             # 回看限制为何开始/解除
python3 -m mcs timeline --entity EQ-SIG-K17              # 设备相关全部事件
python3 examples/demo.py                                 # 端到端演练（乱序到达、归属纠错）
```

待处理事项会标明**依据事件**与**需要的确认类型**：

| 事项 | 需要的确认 |
| --- | --- |
| 故障未闭环（尚无检修记录） | 检修处理 |
| 故障未闭环（已报更换/检查完成） | 现场复核 |
| 调度限制生效中 | 调度通告解除（并提示现场事项是否已闭环） |
| 未归属的设备写法 | 确认设备归属（补充或修订别名映射） |
| 无授权恢复表述 | 无需操作——不构成运行许可 |

## 别名与归属维护

```bash
python3 -m mcs alias-add DC-5 EQ-SW-05 --confirm --by 值班员A   # 新写法登记
python3 -m mcs alias-revise 南二段 SEC-K30 --by 值班长          # 修订映射（历史不变）
python3 -m mcs reattribute EV-00012 EQ-SW-05 --reason "现场核对" --by 值班员A
python3 -m mcs reattr-confirm RA-0001 --by 值班长B              # 确认后生效
python3 -m mcs event EV-00012                                   # 查看归属历史
```

## 记录格式

JSONL（每行一条）或 JSON 数组。字段：`id`、`kind`
（`contractor` / `dispatch` / `field_check`）、`text`，可选
`recorded_at`、`notice_id`、`author`、`lang`。重复 `id` 自动跳过。

演练资料：`data/rail.json`（既有小样例）、`data/shift_handover.jsonl`
（合成记录，到达顺序已打乱，含归属错误与未知写法场景）。合成记录仅用于
演练文本整理。

## 代码结构

- `mcs/models.py` — 记录、事件、实体、别名映射、归属修订
- `mcs/extraction.py` — 中/英/拼音缩写规则抽取（含授权门槛与条件式抑制）
- `mcs/aliases.py` — 别名注册表（确认/修订/版本）
- `mcs/store.py` — 只追加事件库与归属修订
- `mcs/state.py` — 限制生命周期与待处理事项归算
- `mcs/query.py`、`mcs/cli.py` — 值班查询与命令行
- `mcs/seed.py` — 种子实体与别名（按现场台账维护）

本地资料检查使用 Python 标准库运行 `python3 -m unittest discover -s tests -v`。
