@echo off
chcp 65001 >nul
echo 把 MIDI 文件放进 in 文件夹后，运行本脚本。
echo 本脚本会使用 Soma 资源包映射：mappings/soma_gm.json
echo 进游戏前请确认已经启用 Soma 资源包。
echo v0.6 会读取 MIDI BPM，提示推荐 /tick rate，并修正玩家位置，并按音符长度自动选择短音/长音。
echo.
python run_all.py --mapping mappings/soma_gm.json
pause
