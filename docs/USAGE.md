# midi2mc v3.0.0 使用指南

## GUI 快速开始

```bash
python -m midi2mc --gui
```

Windows 也可以双击 `run_gui.bat`。GUI 支持选择 MIDI 文件、`.m2mc.json` 项目配置、输出目录、Show ID、Preset，并可以直接编辑 quality、show_fx、stage_layout、stage_template、Safe Mode、舞台粒子、report、zip、Soma 长音和鼓组等配置。点击“分析 MIDI”可查看摘要、风险等级、推荐 tick rate 和游戏内命令；生成完成后可打开输出目录或 report.html。

## 最短路径

```bash
python -m midi2mc song.mid --preset vanilla_machine --out output
```

游戏内：

```mcfunction
/reload
/function <show_id>:setup
/tick rate <推荐值>
/function <show_id>:play
```

## Preset

```bash
python -m midi2mc --list-presets
```

推荐工作流：

```bash
# 第一次测试
python -m midi2mc song.mid --preset vanilla_clean

# 正常原版演出
python -m midi2mc song.mid --preset vanilla_machine

# 更明显的演出效果
python -m midi2mc song.mid --preset vanilla_fx

# 大型 MIDI 先保守生成
python -m midi2mc song.mid --preset vanilla_safe

# Soma v20 高级音源
python -m midi2mc song.mid --preset soma_concert
```

Preset 会自动设置 sound engine、stage profile、stage layout、quality、show_fx、piano_roll 等常用选项。

## HTML 报告

v1.9 默认生成 `report.html`，包括：

- MIDI 摘要
- 风险等级
- 推荐 tick rate
- 使用的 preset
- 轨道/声道/乐器分组
- Soma 使用报告
- 游戏内执行命令

不想生成报告：

```bash
python -m midi2mc song.mid --no-report
```

## 项目配置

```bash
python -m midi2mc --write-project-template my_song.m2mc.json
python -m midi2mc --project my_song.m2mc.json
```

项目文件支持：

```json
{
  "preset": "vanilla_fx",
  "midi": "song.mid",
  "show_id": "my_song",
  "out": "output",
  "tick_rate": "auto",
  "report_html": true
}
```

## 原版舞台

v1.9 保留 Pulse Stage：setup 干净，音符触发时临时生成音符盒模块，保持数 tick 后清理。节拍器灯仍然存在，但移动播放头和 actionbar Bar/Beat 已移除。

## Safe Mode

```bash
python -m midi2mc song.mid --safe-mode
```

或者：

```bash
python -m midi2mc song.mid --preset vanilla_safe
```

Safe Mode 会偏保守：低质量、较低同 tick 复音上限、关闭 Show FX / Piano Roll / 舞台粒子。


## v2.8 原版舞台模板

`stage_template` 支持：

- `pulse`：默认脉冲舞台。
- `classic_line`：经典一排音符盒机器。
- `minimal`：极简 marker/粒子舞台，方便自己装修。

命令示例：

```bash
python -m midi2mc song.mid --stage-template classic_line
python -m midi2mc song.mid --stage-template minimal
```


## v2.9 FX Profile

`show_fx` 和 `fx_profile` 是两层设置：

- `show_fx`：选择效果层，支持 `none`、`lightshow`、`fireworks`、`both`。
- `fx_profile`：选择视觉风格，支持 `clean`、`redstone`、`concert`、`magic`。

推荐组合：

```bash
python -m midi2mc song.mid --preset vanilla_redstone
python -m midi2mc song.mid --preset vanilla_magic
python -m midi2mc song.mid --show-fx lightshow --fx-profile clean
python -m midi2mc song.mid --show-fx both --fx-profile concert
```

`clean` 最稳，`redstone` 最有机器感，`concert` 适合常规演出，`magic` 更适合幻想/OST 风格 MIDI。
