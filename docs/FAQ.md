# midi2mc v1.9.0 FAQ

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
