# 首次领取与本机保存

完整 Data URL 可能超过宿主的工具输出上限，直接插入 JavaScript 代码还可能超过执行脚本长度限制。下面的接线先把原始对象作为本机临时 JSON 数据写入，再由短脚本保存文件，只把回执交给模型；不依赖模型抄写、解码或补全 base64。`save-results.mjs` 通过进程 stdin 调用同包的 Python 保存器，不把结果或凭据放进 shell 命令行，也不调用任何生成或领取接口。

## Codex 程序化工具编排

先发现当前运行时真正的 MCP、本机文件写入和 JavaScript 工具名称。下面以已公布的 `functions.exec` / `apply_patch` / `mcp__node_repl__js` 为例；命名空间按实际工具替换，不能猜测前缀。`helperPath` 使用本 SKILL.md 所在插件根目录下 `scripts/save-results.mjs` 的真实绝对路径。通过宿主依赖工具或本机命令取得真实 Python 可执行文件的绝对路径，作为 `pythonPath`；不要假设 JavaScript 执行器的 PATH 与终端相同。

先在本机 JavaScript 工具中用 `node:fs/promises.mkdtemp` 和系统临时目录创建本次独用目录，取得其中 `result.json` 的绝对路径 `handoffPath`。只输出该小型路径，不领取结果。该文件只用于本机交接，不上传到平台或 OSS。

在任务已成功且 `deliveryStatus=available` 后，用**一次**程序执行领取和保存：

```javascript
const taskId = "<当前任务的真实 taskId>";
const helperPath = "<插件根目录的绝对路径>/scripts/save-results.mjs";
const pythonPath = "<实际 Python 可执行文件的绝对路径>";
const handoffPath = "<本次独用临时目录>/result.json";
const downloadContext = {}; // 按下文规则填入已掌握的真实来源和完成时间，未知字段省略
const received = await tools.mcp__mmuuai__mmuu_get_result({ taskId });
store("mmuu_received_" + taskId, received);
await tools.apply_patch("*** Begin Patch\n*** Add File: " + handoffPath +
  "\n+" + JSON.stringify(received) + "\n*** End Patch");
const saved = await tools.mcp__node_repl__js({
  code: `var mmuuSaveFs = await import("node:fs/promises");
var mmuuReceived = JSON.parse(await mmuuSaveFs.readFile(${JSON.stringify(handoffPath)}, "utf8"));
var mmuuHelperUrl = (await import("node:url")).pathToFileURL(${JSON.stringify(helperPath)}).href;
var mmuuSaver = await import(mmuuHelperUrl);
var mmuuReceipt = await mmuuSaver.saveReceivedResult(mmuuReceived, ${JSON.stringify({pythonCommand:pythonPath,downloadContext})});
if (mmuuReceipt.status === "saved") await mmuuSaveFs.unlink(${JSON.stringify(handoffPath)});
nodeRepl.write(mmuuReceipt);`,
  timeout_ms: 180000,
  title: "保存 MMUUAI 平台生成结果",
});
for (const block of saved.content ?? []) {
  if (block.type === "text") text(block.text);
}
```

默认直接保存到系统下载目录 `MMUUAI/`，不另建任务 ID 文件夹。用户指定目录时，给 `saveReceivedResult` 的第二个参数增加 `outputDir: 用户指定的绝对目录`，仍用 `JSON.stringify` 把选项作为数据传递；不要用字符串拼接构造 shell 命令。明确要求不保存时不调用保存器，也不创建结果交接文件。

命名遵循站内 `platformGeneratedDownloadName`：来源名清洗并保留最多 24 个 Unicode 字符，类型使用“图片/视频/音频/文本/文件”，时间按 Asia/Singapore，扩展名优先使用实际 MIME。用第二个参数的 `downloadContext: {sourceName, completedAt}` 传递已掌握的真实命名事实，不无故省略已知信息。普通直接模型任务应保留创建前冻结的详情名称作来源标签；只有首次读到 `resourceKind=model`、`succeeded` 且 `deliveryStatus=available` 的正常完成记录时，当前服务的 `updatedAt` 才与完成时间同事务，应在领取前保留作命名时间。不要使用领取后 `delivered` 的更新时间，也不要把工作流/技能的聚合更新时间冒充每个输出的完成时间。没有真实上下文时省略字段，让命名器使用与站内函数一致的默认来源和当前命名时间，不编造歌曲标题。

旧版 MCP 未返回站内冻结来源、每个工作流输出时刻或完整音乐标题时，只能保证命名规则一致，不能声称每个历史/复杂结果与网站逐字同名。同名文件保留已有内容并加后缀，新目录规则不迁移旧文件。

这段代码必须在拿到完整 `received` 的同一次执行中运行。不要先输出 `received`，也不要把工具输出中已经出现的截断片段拼成新 JSON。文件写入工具按原始字符串写入 JSON，不把它当代码执行。保存工具失败时，从 `load("mmuu_received_" + taskId)` 或保留的交接文件取原对象，只重试本机保存步骤；不要重跑包含 `mmuu_get_result` 的整段代码。已有本机文件时优先使用实际路径，不重复下载。只有保存成功才删除本次确切的交接文件；失败时保留供补存，不删除其他文件。

## 其他宿主与恢复

其他宿主用能够访问原始 MCP 返回的程序或文件工具，把完整 JSON 直接通过 stdin 交给 `scripts/save-results.py`。保存器支持直接结果、`structuredContent`、`structured_content`，以及包含 JSON 结果的 MCP 文本外壳。不要把全部结果先放进模型上下文再转交。

如果原对象已经不可用，查询 `mmuu_get_result_references({taskId})`。将返回的完整引用对象直接交给同一保存器补存，只完成已授权的首次交付，不创建新任务。没有上游链接的内联图片无法凭空补全；如实报告已核验的缺失，不重复领取、不自动重新生成。

保存回执仅包含本机路径、类型、字节数、摘要和失败码，用于内部核验，不要求在最终正文重复输出。正常成功时直接用实际本机文件预览图片；不附“已保存”“已结算”等文字或重复费用。用户问保存位置时再给路径，失败或部分成功则明确说明。需要报告保存成功时，必须有 `saved` 回执且文件确实存在。

音视频用宿主媒体嵌入格式展示真实本机绝对路径。若内嵌播放未确认支持，保存后自动调用已有预览工具打开主结果；Codex 使用 open_in_codex 的 target.type=file 与实际路径。没有该工具时不伪造已打开，也不为展示重新生成、重复下载或启动系统播放器。
