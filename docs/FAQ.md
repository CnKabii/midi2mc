# midi2mc v3.0.0 FAQ

## 为什么现在优先原版？

原版不需要资源包，传播门槛最低。Soma 仍然保留，但作为高级音源模式。

## v1.9 为什么去掉 actionbar Bar/Beat？

实测节拍器灯已经能表达节奏，actionbar 文字会占 UI，长期播放时也容易烦。所以 v1.9 移除文字提示，只保留舞台节拍灯。

## 为什么去掉移动播放头？

播放头和节拍器信息重复，而且会持续刷一排灯。v1.9 保留更清爽的 beat meter。

## Preset 和 .m2mc.json 有什么区别？

Preset 是内置风格；`.m2mc.json` 是项目文件。你可以在项目文件里写 `"preset": "vanilla_fx"`，再保存其它自定义设置。

## report.html 有什么用？

它是给玩家和开发者看的生成报告：曲目信息、风险、tick rate、乐器分组、Soma 报告都在里面。反馈 bug 时建议同时提供 `report.html` 和 `midi2mc_manifest.json`。

## Soma 为什么不加 soma:？

当前 Soma v20 示例使用裸 sound event，例如 `2.66`、`2c.66`，并使用 `voice` 分类，所以 midi2mc 也按这个格式输出。

## 复杂 MIDI 卡顿怎么办？

先用：

```bash
python -m midi2mc song.mid --preset vanilla_safe
```

确认能播放后再改成 `vanilla_machine` 或 `vanilla_fx`。

## 怎么打开 GUI？

运行：

```bash
python -m midi2mc --gui
```

Windows 用户也可以双击 `run_gui.bat`。如果 Python 环境没有 tkinter，GUI 会无法启动；这时可以继续使用 `python -m midi2mc` 的交互式向导。


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


## FX Profile 是什么？

`show_fx` 决定开不开灯光/烟花层，`fx_profile` 决定这些效果看起来是什么风格。

- 想少一点粒子：用 `--fx-profile clean`。
- 想要红石机器感：用 `--fx-profile redstone`。
- 想要默认演出感：用 `--fx-profile concert`。
- 想要魔法/幻想感：用 `--fx-profile magic`。

如果担心性能，先用 `show_fx=lightshow` 或 `safe_mode=true`，不要一开始就开 `both`。
