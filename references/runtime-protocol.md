# 运行协议与最小数据结构

## 新渠道队列

先在新制作目录运行 README 中的 `channels.py select`。使用贞贞 AI 或晨羽时，队列保留原 `window_id`、`video_path`、`prompt_path`、角色顺序、实测 `generation_frames` 与 `generation_fps`。首次 `prepare` 自动写入所选渠道的 `profile`，无需提供 RH 的 `schema_path`。照常完成身份及动作复核，再执行 `check` 和 `run`。输入摘要绑定渠道与素材；已付费任务按原 ID 查询。每个新渠道各有一个本机共享台账，每个账户最多三项在途。下文的 RH 应用号与节点表仅供选择 RH 时使用。

## 初始化后

在新的运行目录使用脚本。Python需要av、Pillow；配置本机FFmpeg/FFprobe，或用源包工具。`runtime.json` 的 `ffmpeg_path` 控制解码，`encoder_path` 独立选择合片编码器；环境变量为TROUBLEMAKER_FFMPEG、TROUBLEMAKER_FFPROBE、TROUBLEMAKER_ENCODER，不借APT环境设置。配置路径有误直接报错，不能悄悄回退。

将已有用户制作请求写入 `production_request` / `production_authorized:true`，记录 `appearance_policy` 中明确的画风、耳麦等。这只是忠实记录已有授权，不增加确认流程。凭证用RH_API_KEY或RH_API_KEY_FILE或runtime.api_key_file，文件必须在项目与安装技能之外；没有跨技能默认Key。共享账本默认位于Codex私有目录video-replacement-skill-factory/tasks.sqlite，同一RH账号所有项目使用同一ledger/account_alias，默认default，不能为绕过3槽另起别名。不要输出私有请求、回执、凭证或signed URL。

`identity-checks.json` 初始configured=false。由实际两张参考图确定每角色required/forbidden特征，填入 `[特征名,[英文可接受表达,...]]`；label和reference_sha256绑定本轮图。配置后设configured=true。`validate_prompts.py` 验证原六段结构、Picture角色及本轮特征；样例球衣/红花袄不进入当前校验。remove_text只有本轮要求去文字时才开启。

## 队列、试片与三并发

`approved-queue.json` 初始 `{"jobs":[]}`。先核实当前公开应用schema快照，只支持已接好的ai单人2107844752011010050、双人2107845954833907713。cn或新接口需要另行核实，不能将ai请求发往cn。没有任何此次升级付费测试。

单条job示例（示意路径，不能未分析就提交）：

```json
{
  "window_id":"001_A", "source_segment":"001",
  "hypothesis":"完整原动态，按本轮参考图锁定两人身份",
  "video_path":"补齐生成用/001 39.mp4",
  "prompt_path":"提示词/001.txt",
  "reference_paths":["替换用参考图/一号.png","替换用参考图/二号.png"],
  "schema_path":"接口快照/dual.json",
  "generation_frames":39,"generation_fps":"24","pilot":true,
  "risk_class":"ordinary",
  "profile":{"kind":"legacy-ai-app","app_id":"2107845954833907713","instance_type":"plus",
    "resolution_selector":{"aspect_ratio":"16:9 (Widescreen)","megapixels":0.8,"aspect_node_ids":["115","214"]}}
}
```

067的risk_class必须back-turn-occlusion，102必须native-dissolve。普通试片不能放行这些风险路线。调用 `troublemaker_runtime.pilot_route(entry)` 取得绑定两图/外观/源合同/profile/角色/风险的键，`runtime.pilot_reviews[route]` 包含route、status、notes、output和output_sha256；由真实观看通过后填写。新身份/角色对调/策略改变会失效。

执行 `python troublemaker_runtime.py prepare`，只为改变的输入生成digest并设语义pending，保留未变审批；只解码没有当前媒体证明的视频。实际检查后填job.semantic_review={status:'passed',input_digest:当前digest,notes:实际结论}，将window_id加入runtime.approved_segments。`check`无网络验证，`run`执行，`status`查看账本。`run --once`执行一个调度tick。所有已加载候选不可改输入，要另建版本ID；恢复后按旧ID查询。

tick顺序为查询已在途→补足账号可用槽→下载。UNKNOWN占槽且阻止新增；同输入3次执行故障暂停检查，**不等于视觉总重试上限**。视觉修复由代理建立新候选，记录不同假设/改变项；同一段只剩难点时准备三种有依据的方案，不能仅换ID复制同请求。已通过段放入accepted_segments后停止新提交；held_windows只暂停指定候选。下载及原生解码错误只做本地恢复。

## 输入派生与证据

所有完整输入实际PTS/帧数/音频都检查，含padding总长≤10秒。派生输入需source_contract_path，其合同有source_segment、method、action_frames、source_action_review、dependency_paths。单角色分阶段还需edit_roles、preserved_roles、input_candidate_sha256、preserved_identity_review及 `preserved_identity_evidence:{path,sha256}`。证据必须绑定输入candidate_sha256、两图reference_sha256_by_role、preserved_roles、完整reviewed_frame_range=[0,输入帧数-1]。

通用审查文件格式：schema_version=1、status='passed'、reviewer、findings、artifacts=[{path,sha256}]。这些字段记录真正完成的审查，不由导出图程序自动填写。路径属于本项目；不支持把别的项目审批粘过来。

`inspect_compact.py 001_A --native-all` 或加 `--roi-file <JSON数组>`，ROI例如 `[{"box":[100,100,500,600]}]`。所有输出帧都在总览，所有指定ROI按原尺寸逐帧导出；导出仍是pending。每个候选最多10秒；整片使用独立stream_review。修图改变字节后另存版本、重验受影响处，不覆盖证据。

`compare_actions.py 067_A --map <映射JSON>` 使用output_indices逐源帧对应实际输出；067/102禁止省略map。动作审查包含背转、手臂归属、遮挡、切点、尾部；重复或跳过候选帧需要解释，不能为凑帧数偷换动作。

## 最终选择与合片

`制作分析/selected-candidates.json` 必须含001–102。每段owners逐一列source_frame、绝对规范path、output_frame、sha256，源0…keep−1恰好各一次。028必须原片同帧；其余不可用原片或改名的原片SHA代替。每段review_evidence={path,sha256}，其文档须含source_sha256、reference_sha256_by_role、candidate_sha256_by_path、owners_sha256及native_review/action_review/output_clock_review三项通过。owners_sha256按review_contract.py中排序JSON算法计算，不能手填猜测。

067跨44帧的同一候选必须有实测cut_pairs=[{path,source_before:44,output_before:实测值}]，同时写入已哈希证据文档；分别覆盖两侧的候选也要各自核对实际动作。102证据必须含 `native_transition_review:{status:'passed',source_range:[65,81]}`，保留135源帧。若camera_change=true，user_camera_acceptance需要quote和本轮candidate_sha256_by_path；历史接受不通用。

冻结用runtime.accepted_segments[源段]={path,sha256,evidence:{path,sha256}}，对应文档需candidate_sha256、两图SHA、reviewed_frame_range和native/action通过。多候选拼合时先将冻结对象作为派生完整段验收，最终仍按所有实际owners严格验证。冻结是停止新增，不会取消已付费在途任务。

运行 `assemble_verified.py --selection <选择JSON> --name <新版本名> --plan-only` 检查；正式编码先做同参数代表性测试，使用独立encoder_path或--encoder。本地失败保留partial和日志；只有完整SHA、selection/参数绑定的silent证明才能继续无损封装。fragment本身不能任意帧续写。

音频从现成AAC的0开始，无二次19.37秒偏移，不shortest、不反复有损编码。成片必须4779帧/24fps/1920×1078/首PTS0、AAC payload与原音轨相同、署名保留。

`stream_review.py --video <成片> --out <新复核目录> --plan <frame-plan.json>` 两次完整RGB/PTS流读校准，仅保存采样总览及切口原图，完成后发布证据清单；失败目录不会命中缓存，未变完成目录可复用。总览不是全帧身份或原速验收。后台提供视频让用户原速看，记录明确原话、final_sha256、reviewer=USER、范围/例外；新整片不能冒用旧原速通过。
