# TroubleMaker 人物替换技能 / Character Replacement Skill

## 调用入口与优惠

| 平台 | 入口 | 优惠 |
| --- | --- | --- |
| 贞贞 AI | [贞贞 AI 调用](https://www.zzai.app) | 免费 GPT Image 2.6 |
| RunningHub | [国内站](https://www.runninghub.cn?inviteCode=kol01-rh099) · [国际站](https://www.runninghub.ai?inviteCode=rh-v1121) | 每日 3 次免费 H3 及优惠券 |
| 晨羽 | [晨羽调用](https://www.chenyu.cn/console/login?invitationCode=NGT5S4) | T8 专属优惠券，见下表 |

| 晨羽优惠 | 数量或领取条件 | 券码 |
| --- | --- | --- |
| 0.1 = 5 | 300 张 | `W6TGFF` |
| 30 = 45 | 300 张 | `T8AIGC` |
| 50 = 100 | 每位粉丝均可领取，每个账号限领一次 | `50VS50` |

更多镜像陆续更新，可搜索 **t8star**。

## 选择生成渠道

每次收到新的一组参考图，先确认使用 RunningHub、贞贞 AI 还是晨羽。用户已指定时直接采用。恢复已有任务时沿用制作目录中的渠道和任务号。在新制作目录运行以下三条命令中的一条，选择渠道这一步不计费。

```powershell
python channels.py select --provider rh
python channels.py select --provider zhenzhen --key-file "C:\MyPrivate\zhenzhen.key"
python channels.py select --provider chenyu --key-file "C:\MyPrivate\chenyu.key"
```

两种新渠道各自使用所选平台的私有 Key；文件放在技能和制作目录之外。也可以省略 `--key-file`，使用 `ZZ_API_KEY_FILE` 或 `CHENYU_API_KEY_FILE` 指向私有文件。贞贞 AI 使用 `minimax-h3-comfyui-charswap`，把有序图片 URL 写入 `images`，运动视频和帧数放在 `metadata`。晨羽使用已发布的「Wuwu-视频角色替换」工作流，先校验版本，将图片分开上传并按当前镜头角色顺序绑定节点。

每段保留原始动作帧。渠道需要补帧时，仅给 24 fps 提交副本追加末帧，最终仍按原帧表合片。提交中断时，已取得任务号的继续查询；晨羽可用 `python channels.py reconcile --attempt <本地尝试ID>` 恢复原订单。贞贞 AI 在平台核对该镜头的原任务号后，再添加 `--task-id <原任务号>`。

**选择 RunningHub（RH）时需准备 RH 账号、私有 Key 和可用额度。** 贞贞 AI 和晨羽分别使用各自的账号计费。

**The RunningHub route requires an RH account, a private key and available credits.** Zhenzhen and Chenyu use their own accounts and billing.

注册 / Sign up：[海外站 International](https://www.runninghub.ai/?inviteCode=rh-v1121) · [国内站 Mainland China](https://www.runninghub.cn?inviteCode=kol01-rh099)。当前内置运行器使用海外 `runninghub.ai` 接口；国内站链接仅为注册入口，不代表已验证国内接口兼容性。The bundled adapter targets `runninghub.ai`; the mainland link is a registration option, not a claim of verified endpoint compatibility.

**原作者 / Original author：[wuwukasi](https://space.bilibili.com/670281046)**  
**优化作者 / Optimized by：[T8star](https://space.bilibili.com/385085361)**

感谢 wuwukasi 提供原始复刻包、素材组织、提示词规范与许可。本版本在其基础上完善自动化运行、断线恢复、身份与动作检查、合片及复用流程，保留原作者署名与许可。  
Thanks to wuwukasi for the original remake package, source organization, prompt structure and license. T8star extends that work with automation, recovery, identity/action checks and assembly. Original attribution and licensing are retained.

[中文使用指南](#中文使用指南) · [English guide](#english-guide) · [完整安装包 / Full package](https://github.com/T8mars/Trouble-Maker-Replacement-Skill/releases/latest) · [许可 / License](LICENSE.txt)

## 中文使用指南

### 这个技能能做什么？

给 Agent 两张人物参考图，它会基于包内固定的 **TroubleMaker 舞台 MV** 替换两位主角，尽量保留原动作、镜头、舞台和原音轨，并完成分段检查与合片。

这是**固定 TroubleMaker 原片的复刻技能**，不用于直接套用任意新视频。它是供支持 SKILL.md、可运行 Python 和本地媒体工具的 Agent 使用的工作流，不是独立桌面软件，也不是只运行一个命令就自动完成视觉验收的换脸程序。

| 项目 | 说明 |
|---|---|
| 技能英文名 | `troublemaker-character-replacement` |
| 中文名称 | TroubleMaker全自动人物替换复刻 |
| 当前版本 | 1.2.0 |
| 需要提供 | 两张参考图、角色对应关系、画风要求、所选渠道的私有 Key |
| 一号 / 二号 | 一号对应原男主；二号对应原女主，支持互换 |
| 素材结构 | 102段，101段需生成，仅028保持原片 |
| 成片结构 | 4779帧、24fps，约199.125秒，1920×1078 |
| 并发 | 同账号所有项目合计最多3个在途任务 |
| 已测环境 | Windows、Python 3.12.7、PyAV 18.1.0、Pillow 12.3.0 |

### 1. 安装完整技能

从 [Releases](https://github.com/T8mars/Trouble-Maker-Replacement-Skill/releases/latest) 下载 **`troublemaker-character-replacement-v1.2.0.zip`**，解压得到 `troublemaker-character-replacement` 文件夹。

把它交给 Agent 安装，或放进你使用的技能目录。Codex 通常为 `~/.codex/skills/`；配置了 `CODEX_HOME` 时为该目录下的 `skills/`。安装后重新打开技能列表或新建聊天，搜索中文名或英文名。

> **请下载 Release 中命名的完整 ZIP。** 仓库与 GitHub 自动生成的 “Source code / Code ZIP” 只含代码、文档和素材清单，不含源视频、音轨和包内示例图，不能直接制作。完整包保留原许可及整套本项目素材；不包含 FFmpeg 可执行文件。

让 Agent 检查 Python、PyAV、Pillow、FFmpeg 和 FFprobe。手动准备 Python 依赖时，在技能目录运行：

```powershell
python -m pip install -r requirements.txt
python -B scripts/troublemaker_project.py check
```

FFmpeg/FFprobe 需另行安装并加入 PATH，或在运行配置里指定路径。原始运行器的进程锁面向 Windows；其他系统的付费生产流程尚未验证。

### 2. 提供两张图与私有 Key

- 图尽量清晰，脸、发型和服装特征完整；角色多视图也可使用。
- 说明哪张对应原男主、哪张对应原女主。交换两张图即可制作角色对调版。
- 说明画风，例如“平滑卡通，不要求像素风”。舞台耳麦默认保留，其他要求可直接说明。
- 把 API Key 存在**技能目录和制作目录之外的本机私有文件**，只把路径给本地 Agent；也RH 渠道可通过 `RH_API_KEY_FILE` 或 `RH_API_KEY` 环境变量提供。不要写进 GitHub、Issue、README 或公开截图。

### 3. 直接发送这段需求

```text
使用 $troublemaker-character-replacement 制作 TroubleMaker 换角视频。
图1替换原女主，图2替换原男主；使用平滑卡通风格，保留舞台耳麦和原音轨。
API Key 使用我本机私有文件中的配置。
按原镜头处理，每段完整输入和生成时长不超过10秒，同账号保持最多3并发。
完成后给我成片本地地址，以及需要原速检查的重点。
```

Agent 会建立独立制作目录、识别当前人物、完成试片，再批量生成、修复问题段、检查动作与合片。身份和动态质量需要实际检查；发现问题应继续针对性修复，不能只凭“下载成功”宣布完成。

想制作对调版时说：**“沿用这两张图，人物对应关系互换，另建一版。”** 新人物、新映射会重新进行试片与身份检查，不继承旧验收。

### 这次升级解决了什么？

- **恢复不重复付费**：共享任务账本、提交不确定时先核实、下载失败只重下、队列满等待恢复。
- **少做无效串行尝试**：剩余问题段准备不同修复方案，利用账号可用的3个并发槽；不设视觉总重试3次上限，重复失败需改变策略。
- **按原镜头保留动作**：不是机械每5秒切一次；完整输入与生成时长不超过10秒，实际输出时钟单独检查。
- **避免漏换与认错人**：修正087边缘手部、067主角/伴舞与切点、102原生叠化；身份图和验收证据均绑定当前输入。
- **减少重复本地工作**：媒体检查缓存、流式整片复核、编码前测试；本地编码失败不重新付费生成，完整验证过的无声视频可用于重试封装。
- **保留原片结构**：精确恢复4779帧，原AAC音轨直接复制并核对，保留原作者署名和许可信息。

### 常见问题

**只有 Code ZIP，为什么检查提示缺素材？** 下载上方 Release 的完整技能包，保留原目录结构。

**队列满或网络掉线怎么办？** 让 Agent 继续读取当前项目记录并恢复已有任务，不要另开重复提交器，也不要删除任务账本。

**成本固定吗？** 不固定，取决于 所选渠道计费、任务时长和修复次数。账号、余额与授权需在制作前确认；不承诺固定币数或零重试。

**API Key 或成片会上传到这个仓库吗？** 不会。公开范围只包括本技能与完整许可包内的原始素材；私人凭证、任务账本、个人参考图、候选、成片和任何大小写的 ROADMAP.md 都在发布排除范围内。

## English guide

### Choose a generation provider

For each new pair of references, specify **RunningHub**, **Zhenzhen AI** or **Chenyu**. In the new production directory run exactly one of the following commands before preparing the queue. Resume in the same directory with the original account.

```powershell
python channels.py select --provider rh
python channels.py select --provider zhenzhen --key-file "C:\MyPrivate\zhenzhen.key"
python channels.py select --provider chenyu --key-file "C:\MyPrivate\chenyu.key"
```

Use your selected provider’s private key file, stored outside the skill and production folders. Zhenzhen uses the MiniMax H3 charswap model with ordered image URLs. Chenyu uploads a separate asset per role and binds each one to a workflow slot. Short clips receive a temporary final-frame hold when required. The final cut uses the original shot timing and soundtrack. Confirm the role mapping with a pilot before batching.

### Service links and offers

| Service | Access | Offer |
| --- | --- | --- |
| Zhenzhen AI | [Open Zhenzhen AI](https://www.zzai.app) | Free GPT Image 2.6 |
| RunningHub | [Mainland China](https://www.runninghub.cn?inviteCode=kol01-rh099) · [International](https://www.runninghub.ai?inviteCode=rh-v1121) | Three free H3 runs per day, plus coupons |
| Chenyu | [Open Chenyu](https://www.chenyu.cn/console/login?invitationCode=NGT5S4) | T8-exclusive coupons listed below |

| Chenyu offer | Availability | Coupon code |
| --- | --- | --- |
| 0.1 = 5 | 300 coupons | `W6TGFF` |
| 30 = 45 | 300 coupons | `T8AIGC` |
| 50 = 100 | Available to every fan, once per account | `50VS50` |

Search for **t8star** to find new mirror sites as they are added.

### What this skill does

Provide two character reference images to an agent. The skill replaces the two leads in the **fixed TroubleMaker stage MV included in the complete package**, while preserving the source action, shots, stage and original audio as closely as possible.

This is a reusable **agent workflow for this specific source video**, not a general importer for arbitrary videos or a standalone face-swap application. Your agent must support SKILL.md, local files, Python and media tools. Visual review remains necessary.

- Skill ID: `troublemaker-character-replacement`.
- Version: **1.2.0**.
- Role one replaces the source male lead; role two replaces the source female lead. Their reference identities can be swapped.
- Structure: **102 segments, 101 generation segments and one original passthrough (028)**.
- Final timeline: **4,779 frames at 24fps**, approximately **199.125 seconds**, **1920×1078**.
- Account-wide limit: **three active generation tasks**, including tasks in other projects.
- Tested locally on **Windows / Python 3.12.7 / PyAV 18.1.0 / Pillow 12.3.0**. The production dispatcher uses a Windows process lock; production on other operating systems has not been verified.

### Quick start

1. Download **`troublemaker-character-replacement-v1.2.0.zip`** from [Releases](https://github.com/T8mars/Trouble-Maker-Replacement-Skill/releases/latest). Extract the `troublemaker-character-replacement` folder and ask your agent to install it. For Codex, the usual location is `~/.codex/skills/`, or `skills/` under your configured `CODEX_HOME`.
2. Install Python dependencies with `python -m pip install -r requirements.txt`. Install FFmpeg and FFprobe separately, expose them on PATH or configure their paths. Run `python -B scripts/troublemaker_project.py check` inside the installed skill folder.
3. Provide two reference images, the desired role mapping and visual style. Stage headsets are preserved by default.
4. For the RH route, keep your RH key in a private local file **outside the skill and project directories**. Pass its path to your local agent or configure `RH_API_KEY_FILE`; `RH_API_KEY` is also supported. Never publish the key in issues or repository files.
5. Send the request below. The agent prepares a separate project, reviews pilot outputs, generates and repairs segments, checks the motion and assembles the film.

```text
Use $troublemaker-character-replacement to remake TroubleMaker.
Image 1 replaces the female lead; image 2 replaces the male lead.
Use smooth cartoon rendering, preserve the stage headsets and original audio.
Use my private local RH API-key configuration.
Preserve the source shots; keep each complete input and generated clip within 10 seconds.
Use up to three concurrent tasks across the account.
Deliver the local final-video path and specific points for normal-speed review.
```

**Use the named full Release ZIP, not GitHub's automatic Code/Source code ZIP.** The Git tree contains source, documentation and asset hashes. Required footage, audio and original package example images are distributed together in the complete licensed Release bundle. FFmpeg executables are not bundled.

### Reliability and review

The workflow keeps a shared task ledger, recovers existing task IDs before submitting new work, waits for queue capacity and downloads successful results without repaying for them. Uncertain submissions block blind retries.

Shot boundaries and action phases are preserved rather than forcing five-second splits. Both complete inputs and generated clips must stay within ten seconds. Reference identities, pilot reviews, candidate files and selected frames are bound by hashes. Known source-specific issues in segments 067, 087 and 102 have explicit checks.

When only difficult segments remain, the agent prepares distinct repair hypotheses to use the available three slots. There is no fixed three-attempt limit for visual repairs; repeated failures require a changed approach. Encoding failures are handled locally. A verified complete silent video can be remuxed again without generating the video again.

New identities still need pilot and normal-speed review. Cost varies with provider pricing, generation duration and repairs; neither fixed cost nor zero retries is promised. Private credentials, ledgers, personal references, generated candidates, finished videos and ROADMAP.md are excluded from publication.

## 开发与验证 / Development and verification

```powershell
python -B scripts/test_runtime.py
python -B scripts/test_assembly.py
python -B tools/test_publication.py
python -B tools/verify_publish.py --source .
```

运行与合片部分有41项离线回归，覆盖账号3槽、提交中断、下载恢复、人物与时钟失效、切点/叠化、缓存及AAC校验。合成媒体测试不消耗RH币，也不代表下一组人物已经通过验收。发布检查另行验证完整文件清单、素材来源、密钥排除与目标仓库。

The runtime and assembly suites contain 41 offline regression cases. Synthetic media tests make no paid RH calls and do not approve future identities. Publication checks separately verify the allowed file set, original asset provenance, secret exclusions and repository destination.

详细说明 / Details：[SKILL.md](SKILL.md) · [运行协议](references/runtime-protocol.md) · [问题与预防](references/production-lessons.md)。仅此技能发布到本仓库；APT和通用换角工厂各自独立。

Only this TroubleMaker skill belongs in this repository. APT and the general video-replacement factory are separate projects. The repository-specific publication policy is recorded in [publish-policy.json](publish-policy.json).

## 许可与致谢 / License and credits

原始许可完整保留在 [LICENSE.txt](LICENSE.txt)。允许学习、修改及按原许可分发，必须注明 wuwukasi 原作来源和 T8star 所做优化；本版本不是与原作者无关的完全原创。包内第三方视频、音乐、图片的权利归各自权利人，仅限本项目内部复刻使用，不得单独提取传播或用于商业用途。

The original [LICENSE.txt](LICENSE.txt) is retained unchanged. Study, modification and redistribution are subject to that license and attribution requirements. This edition builds on wuwukasi's work; it is not an unrelated original creation. Third-party footage, music and images remain with their respective rights holders and are for internal use within this remake project, not standalone redistribution or commercial use.

- 原作者 / Original author: [wuwukasi · Bilibili](https://space.bilibili.com/670281046)
- 优化作者 / Optimized by: [T8star · Bilibili](https://space.bilibili.com/385085361)
- [T8star · YouTube](https://www.youtube.com/@T8star-Aix/)
- [免费画廊 / Free gallery](https://www.openzhenzhen.com)
- [在线 AI 应用 / RunningHub applications](https://www.runninghub.ai/zh-cn/user-center/1907375370302308353/userPost?inviteCode=rh-v1121)
- [Hugging Face](https://huggingface.co/t8star)

部分注册链接含邀请码 / Some registration links include referral codes.
