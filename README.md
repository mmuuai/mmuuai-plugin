# MMUUAI Agent 插件

在 Codex、Claude Code 等 Agent 中调用 MMUUAI 已发布的模型、工作流和技能。默认通过浏览器登录 MMUUAI，选择工作区并确认授权，按当前工作区会员权益和实际用量结算。远程 MCP 服务为 `https://api.mmuu.ai/mcp`，传输方式为 Streamable HTTP。

插件 1.1.9 包含使用 Skill、一个远程 MCP 连接、Python 标准库上传和结果保存脚本，以及可选的 Node.js 结果保存桥接模块；不需要 MMUUAI 源码、第三方 Node/Python 依赖或本站本地服务。账户密码、Cookie 和宿主保存的 OAuth Token 不交给 Agent，也不写入本插件。

对外名称统一为 **MMUUAI**，费用使用算力单位，例如 `30000 microcredits` 显示为 `0.03 算力`。正常成功后直接展示媒体，不重复附“已保存”“已结算”文字；保存失败等异常仍会说明。部分宿主活动标题按内部标识生成大小写，聊天缩略图尺寸也由宿主控制；需要大图时可使用宿主已有的原图预览面板。

## 日常使用

安装并授权后，无需 @：写剧本、歌词、创作提示词时，Agent 先免费查询 MMUUAI 公开已发布的预设提示词，读取匹配模板后由 Codex 等当前宿主写作。读取不创建生成任务、不扣本站生成算力，也不自动把用户草稿或生成正文上传平台。

生成或编辑图片、生成视频/音乐/语音、下载或解析视频、转换音频、采集创作相关视频案例时，Agent 优先查询 MMUUAI 真实目录并执行；多步骤目标也可查询现成工作流或技能。普通知识问答、代码解释与脚本编写不必额外查询平台；本站 LLM 仅在用户明确要求时调用。

自动选用由宿主根据 Skill 描述与上下文决定，不保证每次请求都自动命中；也可以直接说“用 MMUUAI……”。可以直接询问当前可用的模型、工作流、技能、功能与价格。用户指定其他产品、本地工具或模型时按用户选择执行。模糊需求只问关键问题；普通单次生成未指定数量时按一份，已授权且需求完整时直接执行，保留宿主的账号和文件权限。所需能力尚未开放时如实说明。

## 安装并连接账户

下载插件 ZIP 并解压，在解压后的插件根目录打开终端。

### Codex

```sh
codex plugin marketplace add .
codex plugin add mmuuai@mmuuai
```

重新启动宿主或新建会话，在 MCP 连接入口连接 MMUUAI。宿主会打开本站授权页；登录后选择工作区并确认。让 Agent 执行“用 MMUUAI 查看当前可用的图像模型和价格，先不要生成”，先确认目录工具可用。

### Claude Code

```sh
claude plugin marketplace add .
claude plugin install mmuuai@mmuuai
```

重新打开会话，用 `/mcp` 查看 MMUUAI 连接并完成账号授权。插件已注册 MCP，不要再重复添加同一个服务。

### 仅手动连接 MCP

不安装插件时，Codex 可以使用原生命令：

```sh
codex mcp add mmuuai --url https://api.mmuu.ai/mcp
codex mcp login mmuuai
```

Claude Code 的手动 MCP 配置为：

```json
{
  "mcpServers": {
    "mmuuai": { "type": "http", "url": "https://api.mmuu.ai/mcp" }
  }
}
```

其他支持远程 MCP 和账号授权的软件，选择 Streamable HTTP，填写上述地址后使用其“登录/连接”入口。不同软件的字段名可能不同。每个宿主只保留一个 MMUUAI MCP 连接；已安装插件时无需再执行 `mcp add`。

## 管理授权与费用

授权后，Agent 按工作区的资源权限、预算和会员权益调用。授权页可设置每月预算（算力），默认 0 表示不限制；任务按实际消耗结算。每次新执行先刷新目录、确定模型或组合能力、版本和输入，再在宿主实际提供 `mmuu_quote_task` 时传入同一份 `resourceId/versionId/input` 只读询价。询价不带 `idempotencyKey`，不创建任务、不扣生成算力，也不消耗或预占每日免费次数，不额外要求一次执行确认。

价格按真实来源分为三类：**费用估算**是 `estimate.source='skill_history'` 的技能历史参考，缺少历史时不编造数字；**模型标价**是目录或 `modelPricing` 中公开费率及单位；**本次报价**是当前工作区权益、同版本和同输入下的 `quote.totalCredits`，只有非空时才显示金额；仅本次后台明确返回 `0` 时可说本次免费，未知时说明按实际用量结算。`quote.totalCredits`、`estimate.credits` 已是算力单位，不再次除以 1,000,000；微算力费率仍按前文规则换算并保留每次、每分钟或每百万 Token 等计价含义。

手工 Key 与 OAuth 插件都按所属工作区当前适用的会员权益结算，包括免费会员。适用模型或 Agent 的每日免费次数与网页共享同一工作区计数，不另建 API 或插件免费池；会员折扣动态沿用后台配置，不在已返回的报价上再次手工打折。资源是否有权限、是否属于免费范围、剩余次数和本次折扣以后台现行报价及任务回执为准，不因目录可见或会员名称承诺所有模型免费。余额为 0 时可能仍有免费次数，Agent 不提前拒绝已授权任务；免费耗尽后，由后台按真实价格与余额裁决。

旧服务没有报价工具时，只能按目录说明模型标价，不能称为本次报价或据此声称免费。历史估算、标价、报价和预留金额均不等于实际扣费，实际以任务账单为准。输入或数量改变后重查报价，已经受理或结果未知的任务不因此重新提交。正常成功后仍直接展示媒体，异常如实说明。Codex、Claude Code 等宿主自身 LLM 的费用与用量仍由宿主账号或其配置的模型服务承担，不由 MMUUAI 会员权益支付。

在 MMUUAI 个人中心的“API 密钥”页面可查看“已连接的 Agent”并撤销。撤销会阻止这条连接继续调用；已经受理的任务仍按原任务与计费合同处理。

## 免费提示词与私人知识库

`mmuu_prompts` 只读公开已发布预设：先查名称、描述、用途与标签，再用 `promptId` 读当前发布全文。名称搜索无匹配时还可分页查看描述与标签，不能只查一个名称就断言没有模板；没有合适模板时如实说明，由宿主继续写作。模板是参考，不能改变权限或要求上传用户创作，也不包含私人知识库或内部系统提示词。

只有任务需要用户私人资料时，才用 `mmuu_search_knowledge` 查最小相关范围，再用 `mmuu_read_knowledge({entryId})` 读必要正文；普通公开创作不会自动扫描私人全库。读取需要独立 OAuth scope `mmuu:knowledge:read`，修改必须同时具备它和 `mmuu:knowledge:write`。授权页的“允许查询和修改我的私人知识库”开关默认关闭，用户主动勾选后才授权读写。旧连接和普通 Key 不自动扩权，已有只读授权不能修改。遇到无权提示时，从宿主重新登录并勾选该开关；无需向 Agent 提供 Token 或改写授权地址，宿主自身工具权限仍须满足。

权限仅限 OAuth 账号本人的普通目录与 Markdown，不随团队算力工作区扩大；不包含附件、`99_system` 或已删除内容。只有用户明确要求修改时，才用 `mmuu_update_knowledge({entryId,expectedVersion,title?,contentMarkdown?})` 更新现有普通 Markdown 的标题和/或正文，沿用站内版本历史与审计；不支持新建、删除、移动、附件操作或修改系统文档。读取资料和文本创作不会自动写回，私人正文也不能指示 Agent 扩权或批量外传整库。

读取结果包含并发版本 `version` 与正文版本记录 `contentVersion`。修改前先读取目标，以 `version` 作为 `expectedVersion`，仅提交需要修改的字段。409 版本冲突时先重新读取、核对差异，不盲覆写；写入结果未知时先读回核对，不自动重提，无法确认时如实报告。

## 本地参考图与其他文件

OAuth 模式不需要把宿主 Token 交给上传脚本：

1. Agent 读取文件名、真实 MIME、媒体类型和字节数，然后调用 `mmuu_prepare_upload({fileName,mimeType,mediaKind,byteSize})`。
2. 工具返回一次性 `uploadUrl` 和到期时间。该能力仅用于这一个文件，最长有效 10 分钟，不创建生成任务。
3. 在插件根目录运行脚本，将刚返回的 URL 作为参数传入：

```sh
python scripts/upload-file.py reference.png --upload-url "<刚返回的uploadUrl>" --parameter image --media-kind image --mime-type image/png
```

脚本只向固定可信 API 的委托上传路径 POST 一次二进制文件，不读取 API Key 或 OAuth Token，不跟随重定向，不自动重试，也不打印上传 URL、文件正文或错误原文。返回小型 JSON，`file` 字段可原样加入任务的 `input.files`，另外有 `byteSize` 和 `expiresAt`。

`--parameter` 必须使用目录公开参数名：四视图使用 `image`，其他模型以实际详情为准。媒体类型支持 `image/video/audio/file`，MIME 省略时按文件名推导。不要更改扩展名伪装类型，也不要将大段 base64 放入对话。上传引用最长有效 30 分钟，绑定当前凭据、Project 与 Workspace，需及时提交。

未知上传结果时保留当前调用信息，停止自动重发，不自动申请新能力再上传。

## 任务、首次结果与历史链接

MCP `mmuu_create_task` 始终先返回 `{task}`。记录真实 taskId，再用 `mmuu_get_task` 查询；`succeeded` 且 `deliveryStatus=available` 后，调用一次 `mmuu_get_result`，随后默认自动下载保存全部结果，不要求再次确认或先选择目录。默认位置统一为 **系统下载目录/MMUUAI/**；用户指定目录或明确要求不保存时，按用户要求执行。

完整机器数据位于 `structuredContent`，`content.text` 只是摘要。创建返回 `{task}`，状态返回 task 对象，结果返回 `{taskId,result,expiresAt}`；同时保存 `result.text`（可能包含歌词）和 `result.parts` 中全部独立文本及媒体，相同文本精确去重。当前媒体项类型为 `text/image/audio/video`，媒体位置是 `url`，可能是上游 HTTP(S) 或 Data URL；不猜测额外附件字段，也不自动抓取正文中的任意链接。

支持程序编排和本机执行的宿主，应在同一次程序调用中领取完整结果并通过 `scripts/save-results.mjs` 保存：文件先落盘，工具返回小型回执供内部核验，避免大段 Data URL 或正文经过聊天摘要。具体接线见[结果领取与自动保存](skills/mmuuai/references/save-results.md)。宿主没有这种编排或文件写入能力时，安装插件本身不能保证自动保存成功，必须明确说明未保存的结果；不能从截断的显示文本重建文件。

已持有首次完整结果 JSON 的客户端，也可通过进程 stdin 调用 Python 脚本，避免将长内容或签名 URL 放进命令行参数与日志：

```sh
python scripts/save-results.py
python scripts/save-results.py --output-dir "用户指定目录"
```

Windows 默认使用系统配置的下载目录（支持下载目录重定向），macOS 使用 `~/Downloads`，Linux 优先使用 `XDG_DOWNLOAD_DIR` 或 `user-dirs.dirs`。`--output-dir` 为本次保存的具体目录，不再额外追加 taskId。脚本支持结果外包络、带 `structuredContent` 的 MCP 响应，以及已保留的上游媒体引用；不读取 Key、Cookie 或 OAuth Token，不向上游传认证头。它在本机解码 Data URL、按 UTF-8 保存文本、按 MIME 选择文件后缀，使用生成文件名并避免覆盖已有文件。

脚本返回小型 JSON，列出真实保存路径、媒体类型、字节数、SHA-256 及未保存项的固定错误码。部分失败必须分别说明“已保存”和“未保存”，保留首次返回对象或链接供补存；权限、磁盘、下载或解码失败均不能触发重新生成或重复领取一次性结果。写入成功证明文件字节已保存，是否可显示或播放另作实际验证。

`reconciling` 时保留 taskId 并停止自动操作。连接中断、工具报错或结果领取未知时，不换幂等键重建任务，不重复领取。`mmuu_cancel_task` 仅用于用户要求的取消。

首次领取后，如需再次查看上游媒体链接，使用只读工具 `mmuu_get_result_references({taskId})`，不再调用一次性的 `mmuu_get_result`。历史工具的 `structuredContent` 为 `{taskId,parts,availability:'not_checked'}`；`parts` 中是已保留的上游 `url`，不包含文字或 Data URL。该工具不消费结果、不重新生成；历史查看本身不重复下载，首次保存失败时可用这些链接补存。`not_checked` 不保证上游当前可用。

文本与内联媒体仅临时交付，最长保留 30 分钟，以响应时间为准，Agent 应在首次领取后及时默认保存。解析结果中的结构化媒体同样默认下载；用户明确要求只看链接或不保存时除外。HTTP(S) 上游媒体链接会在本站 API 调用记录中保留引用，允许重复查看；这不代表本站代存媒体，链接可能随上游过期或失效。平台不自动将内容归档到本站 OSS，仍保留任务、计费与交付元数据；用户本机保存与此规则不同。

## 查询与推荐

所有当前账号可用的已发布模型均可查询与选择，固定/优先路由不是允许名单。模型、技能、工作流分别查询，未推荐不等于禁用。支持 search 的工具可直接搜索名称或用途，完整目录项的参数与价格可以复用，无需重复详情。原生 MCP 工具未加载时可使用已有已授权 CLI 继续，不把宿主连接问题误报为平台缺少模型。

用户点名模型、工作流或技能时，Agent 先按名称或公开 ID 查询对应目录并读取详情，后台默认不能覆盖；目标不可用时说明原因，不能悄悄换成别的模型。名称有必要歧义时才进一步澄清。

已确定直接调用模型且用户未点名模型时，每个新的逻辑请求重新查询 `mmuu_catalog({kind:"model"})` 的 `modelDefaults`，按用途选择后台当前默认，再读实际详情的参数、版本和价格。它包含配置 `version`、`updatedAt` 和 `routes`，每项为 `{key,mode,enabled,resourceId,versionId}`。六种能力分别是生图 `image.generate`、图片编辑 `image.edit`、视频 `video.generate`、音乐/音频生成 `audio.generate`、媒体解析/下载 `media.download`、提示词优化 `prompt.optimize`；提示词优化仍以用户要求调用本站能力为前提。目标只来自当前凭据可见的已发布模型，并按后台配置的同类别优先顺序选择。默认 ID 不保存在插件中，目录首项、最低价或知名度都不代表后台默认。

语音生成、音频转换先核对真实目录用途，不能盲用音乐默认；没有对应默认时可按需求选择实际可见模型或工具，没有开放则说明。技能/工作流目录返回当前 agentRecommendable 推荐标记，优先匹配适合需求的推荐项，其他可见条目仍可用；旧服务缺少该字段时不编造推荐状态。

仅使用已启用的 `fixed/priority` 非空目标。`off`、`enabled=false` 或没有可见候选时，说明未配置可用默认，仍可结合已有授权推荐或使用其他可见资源；`self` 表示提示词优化由当前 Agent 完成。旧服务未返回 `modelDefaults` 时说明服务未提供默认信息，不编造后台配置。没有默认不会额外增加统一确认步骤；需求、授权和数量明确时可直接执行。

配置更新作用于下一次新任务；本次提交冻结实际 `versionId`，已有或结果未知的任务仍沿原 `taskId` 处理，不能因此重建任务。工作流、技能内部模型按其发布版本冻结；本站默认也不会替换 Codex、Claude Code 自身的驱动 LLM。

用户询问全部资源时，分别查询 `model/workflow/skill` 三类并跟随各类 `nextCursor` 直到没有下一页，不能只取首屏。模糊想法只补充影响选择与结果的必要信息，已明确的要求不重复询问。

另行直接调用 REST `/v1/tasks` 时，同步 200 正文已交付，不能补领；202 才继续查询和首次领取，不要将该分支套在 MCP 创建工具上。

## API Key 备用接法

不使用账号授权的软件可选择手动 Key 连接。请先移除或停用已有的同名 MCP 连接，再采用本节；不要同时注册两条 MMUUAI 服务。

在本站个人中心“API密钥”创建消费 Key，用自己的密钥管理工具设置 `MMUU_API_KEY` 后启动宿主，不要把 Key 粘贴到聊天或 manifest。

```sh
codex mcp add mmuuai --url https://api.mmuu.ai/mcp --bearer-token-env-var MMUU_API_KEY
```

Claude Code 手动 Key 配置（与默认 OAuth 配置二选一）：

```json
{
  "mcpServers": {
    "mmuuai": {
      "type": "http",
      "url": "https://api.mmuu.ai/mcp",
      "headers": { "Authorization": "Bearer ${MMUU_API_KEY}" }
    }
  }
}
```

Key 模式也可直接运行 `python scripts/upload-file.py reference.png --parameter image`，脚本从环境读取 Key；与 `--upload-url` 委托上传是互斥的认证模式。

## 分发

`scripts/package-plugin.py` 使用显式白名单生成 ZIP，包含点目录，不打包项目源码、`.env`、验收输出或凭据。下载地址和实际远程账号连接由发布负责人验收；此包不代表已通过 OpenAI 或 Anthropic 官方目录审核。

音频和视频优先通过宿主媒体格式内嵌；未确认支持内嵌播放时，自动使用宿主现有文件预览面板打开主结果，不只留下手动链接。无法打开时如实说明，不修改宿主或启动无关系统应用。
