# midi2mc_soma_v0_6

一个极简版 MIDI 转 Minecraft `playsound` 数据包工具。

目标不是工程化，而是像 `gif2mc` 那样：编号脚本、固定目录、每一步都能单独检查。

## 目录

```text
midi2mc_soma_v0_6/
  01_parse_midi.py          MIDI -> temp/notes.json
  02_gen_sound_events.py    notes.json -> temp/sound_events.json
  03_gen_datapack.py        sound_events.json -> out/datapack
  04_analyze_midi.py        辅助查看 MIDI 信息
  05_scan_soma_sounds.py    辅助扫描 Soma sounds.json
  run_all.py                一键执行 01-03
  run_soma.bat              Windows 双击生成 Soma 版

  in/                       放 MIDI 文件
  temp/                     中间 JSON
  out/                      输出数据包和说明
  mappings/vanilla.json     原版音效映射
  mappings/soma_gm.json     Soma GM 编号音效映射
```

## 安装依赖

```bash
python -m pip install -r requirements.txt
```

Windows 也可以双击：

```text
install_requirements.bat
```

## 最简单使用方式

把 `.mid` 或 `.midi` 文件放进 `in/`，然后运行：

```bash
python run_all.py --mapping mappings/soma_gm.json
```

Windows 可以双击：

```text
run_soma.bat
```

生成结果在：

```text
out/datapack/
out/README.txt
out/config.json
```

## 进游戏使用

把 `out/datapack` 文件夹复制到：

```text
.minecraft/saves/你的世界/datapacks/
```

然后进游戏：

```mcfunction
/reload
/function midi2mc:tickrate_hint
```

它会提示推荐值，例如：

```mcfunction
/tick rate 30
```

然后播放：

```mcfunction
/function midi2mc:restart
```

播完如果想恢复原版速度：

```mcfunction
/tick rate 20
```

## Soma 资源包模式

Soma 的 `sounds.json` 主要规律是：

```text
MIDI program 0 + note 60  -> 短音 1.60 / 长音 1c.60
MIDI program 40 + note 60 -> 短音 41.60 / 长音 41c.60
MIDI channel 9 + note 35  -> 0.35
```

也就是说，Soma 不是靠一个音色加 `pitch` 变调，而是已经给很多 MIDI note 准备了独立 sound id。

v0.6 默认按每个音符长度自动选择 Soma 采样：

```text
短音：1.60
长音：1c.60
```

默认阈值是 8 tick。少于 8 tick 的音会走短采样；达到 8 tick 的音，如果该乐器有 `c` 长采样，就会走长采样并生成对应 `stopsound`。

如果某些乐器没有 `c` 长音，会自动回退短音。

## v0.4 的 BPM / Tick Rate 逻辑

v0.3 的错误是：把 `/tick rate 30` 同时用来“生成事件 tick”和“提示用户”。这样会把时间轴搞混。

v0.4 改成：

```text
生成事件 tick：默认固定 20 TPS
MIDI BPM：只用来计算推荐 /tick rate
数据包：只提示，不自动修改世界 tick rate
```

Soma 模式默认使用 `fixed_base_bpm`：

```text
120 BPM -> /tick rate 20
180 BPM -> /tick rate 30
90 BPM  -> /tick rate 15
```

所以你只需要生成一次，然后看 `out/README.txt` 或游戏内 `/function midi2mc:tickrate_hint` 的提示。

## 分步运行

```bash
python 01_parse_midi.py --input in/example.mid --tempo-mode fixed_base_bpm --yes
python 02_gen_sound_events.py --mapping mappings/soma_gm.json --yes
python 03_gen_datapack.py --mapping mappings/soma_gm.json --yes
```

## 扫描 Soma sounds.json

如果想先检查 Soma 的 `sounds.json`：

```bash
python 05_scan_soma_sounds.py --sounds-json sounds.json --yes
```

会生成：

```text
temp/soma_sounds_index.json
out/soma_sound_report.txt
```


## v0.5 / v0.6 的声音位置和长短音判断

v0.5 改了两个很关键的播放细节，v0.6 又补上了“短音/长音自动判断”。

第一，声音默认在玩家当前位置播放。生成的命令类似：

```mcfunction
execute as @a at @s run playsound 1c.60 voice @s ~ ~ ~ 0.8 1
```

这样每个玩家听到的声音都来自自己所在那一格，不会跑到数据包函数执行坐标附近。

第二，v0.6 不再无脑使用 `c` 长音，而是按 MIDI duration 自动判断：

```text
duration < 8 tick   -> 短采样，例如 1.60，不生成 stopsound
duration >= 8 tick  -> 长采样，例如 1c.60，并按 note_off 生成 stopsound
```

例如某个音在 tick 40 开始，持续 20 tick，那么会大致生成：

```mcfunction
# tick_000040.mcfunction
execute as @a at @s run playsound 1c.60 voice @s ~ ~ ~ 0.8 1

# tick_000060.mcfunction
execute as @a run stopsound @s voice 1c.60
```

如果同一个 sound id 有重叠，脚本会合并重叠区间，尽量避免前一个音的 `stopsound` 把后一个同音高也切掉。

可调参数在 `mappings/soma_gm.json` 里：

```json
"sound_position_mode": "player",
"generate_note_stops": "soma_long_only",
"note_stop_delay_ticks": 0,
"soma": {
  "variant": "auto",
  "long_note_min_ticks": 8
}
```


## 注意

- 第一版只用 `playsound`，不生成音符盒、红石、结构方块或 schematic。
- 默认按 Minecraft Java 1.21+ 的 `data/<namespace>/function/` 目录生成。
- 如果游戏提示 `pack_format` 不匹配，改 `mappings/*.json` 里的 `pack_format`，再重新运行。
- 大 MIDI 会生成很多 `.mcfunction`，建议先用短 MIDI 测试。
- Soma 模式会在 `/function midi2mc:stop` 和 `/function midi2mc:restart` 时执行 `execute as @a run stopsound @s voice`，同时也会给 c 长音按 duration 生成精确 stopsound。
