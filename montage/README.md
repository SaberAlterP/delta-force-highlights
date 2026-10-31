# montage · 音乐卡点剪辑（独立模块）

把集锦包里的高光按一首歌自动剪成卡点片：击杀开枪落在歌最重的重音上，镜头切在拍点上，长时间无击杀自动快进。
不依赖 backend，可单独用命令行 / Python 调用；网页「集锦剪辑」由 `backend/app/services/montage_studio.py` 包了一层，剪辑助手的工具在 `montage_agent.py`。
素材也可以是任意视频：`kills.from_files(文件列表, cfg, manual={文件: [开枪帧秒数]})`。

依赖：ffmpeg（PATH）、numpy、librosa。歌曲用 mp3/flac/wav（网易云 .ncm 是加密格式，需自行转换）。

## 四步（每步输出 JSON，可人工或 agent 修改）

```powershell
cd 仓库根目录
python -X utf8 -m montage analyze --song "歌.mp3" --work W     # -> W/song.json   节拍/小节线/重音排序
python -X utf8 -m montage kills   --root <集锦文件夹> --work W     # -> W/kills.json  每段高光的开枪画面时间
python -X utf8 -m montage plan    --work W                     # -> W/timeline.json
#   （可选）改 timeline.json：换片段、删镜头、改 kills[].at、改 transition_in……然后：
python -X utf8 -m montage retime  --work W                     # 重算变速；不可行的改动会提示
python -X utf8 -m montage render  --work W --out 成片.mp4
```
一键：`python -X utf8 -m montage run --song 歌.mp3 --root <集锦文件夹> --out 成片.mp4`

任意参数都能覆盖：`--set plan.duration=45 --set plan.kills_per_shot=2 --set render.hq=true`，或 `--config my.json`。
全部参数和默认值见 [config.py](config.py)。

## 规则（都可配置）

| 参数 | 默认 | 说明 |
|---|---|---|
| `plan.kills_per_shot` | 不限 | 一个镜头最多收几个击杀 |
| `plan.chain_max_gap` | 20s | 同镜头两次击杀素材间隔超过就换镜头；`null` = 不限（中间自动快进） |
| `plan.speed_min` / `speed_max` | 1.0 / 1.35 | 两次击杀间的变速范围（1.0 = 不慢放） |
| `plan.ff_speed_max` | 4.0 | 快进最高倍速；结构：原速 → 匀速快进 → 平滑减速 → 原速 |
| `plan.first_lead` / `lead` | 9~18s / 4~9s | 击杀前留的前因 |
| `plan.transition` + `transition_every` | cut / 0 | 每隔几个切点用一次 push / impact / flash / dip / whip 转场 |
| `render.opening` / `title` | fade_blur / 空 | 开头：fade_blur / zoom / flash / none，可加标题文字 |
| `render.ending` / `fade_out` | fade / 1.5s | 结尾：fade / blur / none |
| `render.intro_video` / `outro_video` | 无 | 自定义片头 / 片尾视频，接在成片前后 |
| `kills.av_offset` | 0.12s | 录像声音比画面晚多少 |

## timeline.json

```json
{"song": "W/song.wav", "song_start": 0, "duration": 57.5,
 "shots": [{"file": "...高光.mp4", "start": 0, "end": 17.52,
            "kills": [{"src": 62.43, "at": 16.014}],
            "transition_in": "cut",
            "segments": [{"src": [0.2, 12.68], "speed": [1.49, 1.0]}, ...]}]}
```
`kills[].src` 是片段内开枪帧，`at` 是它落在成片第几秒；`segments` 由 `retime` 自动推出。

## 关键经验（为什么这样做）
- 重音：节拍网格要对准底鼓（librosa 默认常错半拍）；"重"看与前 2 秒（避开最近 0.3s 弱起）的反差；drop 后连续几拍都重时取第一拍。
- 击杀时刻：官方 `time` 是倒地者最终死亡时刻，可能比打倒那一枪晚 0.2~2s；用 `verification_time`（画面提示）前最后一声枪响。
- 用户偏好：不慢放卡点、击杀不加缩放/震屏、歌从头放、每个击杀要有前因。
