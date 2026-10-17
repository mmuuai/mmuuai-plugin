/** Save a complete in-memory MCP result. Never fetch or recreate a task. */
import { spawn } from "node:child_process";
import { isAbsolute } from "node:path";
import { fileURLToPath } from "node:url";

const SCRIPT = fileURLToPath(new URL("./save-results.py", import.meta.url));
const PYTHON_ENTRY = `import json,os,runpy,sys
script=sys.argv[1]
if not os.path.isfile(script):
    print(json.dumps({"status":"failed","code":"MMUU_SAVE_BRIDGE_HELPER_FILE_UNAVAILABLE","resultRefetchAttempted":False}))
    sys.exit(1)
sys.path.insert(0,os.path.dirname(script))
sys.argv=sys.argv[1:]
runpy.run_path(script,run_name="__main__")`;
const TASK_ID = /^tsk_[A-Za-z0-9_-]{16,80}$/;
const CODE = /^MMUU_SAVE_[A-Z0-9_]+$/;
const TYPES = new Set(["text", "image", "audio", "video", "file"]);
const MAX_RECEIPT_BYTES = 262_144;
const record = (value) =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const localPath = (value) =>
  typeof value === "string" && !value.includes("\0") && isAbsolute(value);
const partIndex = (value) => Number.isSafeInteger(value) && value >= -1;

function failure(code) {
  return {
    status: "failed",
    code,
    resultRefetchAttempted: false,
    generationAttempted: false,
  };
}

function receipt(value, exitCode) {
  if (
    !record(value) ||
    !["saved", "partial", "failed", "empty"].includes(value.status) ||
    value.resultRefetchAttempted !== false ||
    value.generationAttempted === true ||
    value.mediaDecoded === true
  )
    return null;
  if ((value.status === "saved" ? 0 : 1) !== exitCode) return null;
  if (
    value.code !== undefined &&
    (typeof value.code !== "string" || !CODE.test(value.code))
  )
    return null;
  if (
    value.taskId !== undefined &&
    (typeof value.taskId !== "string" || !TASK_ID.test(value.taskId))
  )
    return null;
  if (value.directory !== undefined && !localPath(value.directory)) return null;
  const saved = [],
    failures = [];
  if (!Array.isArray(value.saved ?? []) || !Array.isArray(value.failures ?? []))
    return null;
  for (const item of value.saved ?? []) {
    if (
      !record(item) ||
      !partIndex(item.partIndex) ||
      !TYPES.has(item.type) ||
      !localPath(item.path) ||
      typeof item.mimeType !== "string" ||
      !/^[a-z0-9!#$&^_.+-]+\/[a-z0-9!#$&^_.+-]+$/i.test(item.mimeType) ||
      !Number.isSafeInteger(item.byteSize) ||
      item.byteSize < 0 ||
      typeof item.sha256 !== "string" ||
      !/^[0-9a-f]{64}$/.test(item.sha256)
    )
      return null;
    saved.push({
      partIndex: item.partIndex,
      type: item.type,
      path: item.path,
      mimeType: item.mimeType,
      byteSize: item.byteSize,
      sha256: item.sha256,
    });
  }
  for (const item of value.failures ?? []) {
    if (
      !record(item) ||
      typeof item.code !== "string" ||
      !CODE.test(item.code) ||
      (item.partIndex !== undefined && !partIndex(item.partIndex)) ||
      (item.httpStatus !== undefined &&
        (!Number.isInteger(item.httpStatus) ||
          item.httpStatus < 100 ||
          item.httpStatus > 599))
    )
      return null;
    failures.push({
      ...(item.partIndex === undefined ? {} : { partIndex: item.partIndex }),
      code: item.code,
      ...(item.httpStatus === undefined ? {} : { httpStatus: item.httpStatus }),
    });
  }
  if (
    (value.status === "saved" && (!saved.length || failures.length)) ||
    (value.status === "partial" && (!saved.length || !failures.length)) ||
    (value.status === "failed" &&
      (saved.length || (!failures.length && !value.code))) ||
    (value.status === "empty" && (saved.length || failures.length))
  )
    return null;
  return {
    status: value.status,
    ...(value.code ? { code: value.code } : {}),
    ...(value.taskId ? { taskId: value.taskId } : {}),
    ...(value.directory ? { directory: value.directory } : {}),
    saved,
    failures,
    resultRefetchAttempted: false,
    generationAttempted: false,
    retrySavingFromOriginalResult: value.retrySavingFromOriginalResult === true,
    mediaDecoded: false,
  };
}

export async function saveReceivedResult(payload, options = {}) {
  if (!record(options)) return failure("MMUU_SAVE_BRIDGE_OPTIONS_INVALID");
  const { outputDir, pythonCommand, downloadContext, skipPartIndexes } =
    options;
  let input;
  try {
    if (!record(payload)) return failure("MMUU_SAVE_BRIDGE_INPUT_INVALID");
    if (downloadContext !== undefined && !record(downloadContext)) {
      return failure("MMUU_SAVE_BRIDGE_OPTIONS_INVALID");
    }
    if (
      skipPartIndexes !== undefined &&
      (!Array.isArray(skipPartIndexes) ||
        !skipPartIndexes.every(partIndex) ||
        new Set(skipPartIndexes).size !== skipPartIndexes.length)
    ) {
      return failure("MMUU_SAVE_BRIDGE_OPTIONS_INVALID");
    }
    const naming = {};
    for (const key of ["sourceName", "completedAt"]) {
      if (downloadContext?.[key] !== undefined) {
        if (
          downloadContext[key] !== null &&
          typeof downloadContext[key] !== "string"
        )
          return failure("MMUU_SAVE_BRIDGE_OPTIONS_INVALID");
        naming[key] = downloadContext[key];
      }
    }
    input = JSON.stringify(
      downloadContext === undefined && skipPartIndexes === undefined
        ? payload
        : {
            receivedResult: payload,
            downloadContext: naming,
            ...(skipPartIndexes === undefined ? {} : { skipPartIndexes }),
          },
    );
    if (typeof input !== "string")
      return failure("MMUU_SAVE_BRIDGE_INPUT_INVALID");
  } catch {
    return failure("MMUU_SAVE_BRIDGE_INPUT_INVALID");
  }
  if (
    (outputDir !== undefined &&
      (typeof outputDir !== "string" ||
        !outputDir.trim() ||
        outputDir.includes("\0"))) ||
    (pythonCommand !== undefined &&
      (typeof pythonCommand !== "string" ||
        !pythonCommand.trim() ||
        pythonCommand.includes("\0")))
  ) {
    return failure("MMUU_SAVE_BRIDGE_OPTIONS_INVALID");
  }
  return new Promise((resolve) => {
    let child,
      settled = false,
      tooLarge = false,
      output = "",
      outputBytes = 0;
    const finish = (result) => {
      if (!settled) {
        settled = true;
        resolve(result);
      }
    };
    try {
      child = spawn(
        pythonCommand ?? (process.env.MMUUAI_PYTHON || (process.platform === "win32" ? "python" : "python3")),
        [
          "-X",
          "utf8",
          "-B",
          "-c",
          PYTHON_ENTRY,
          SCRIPT,
          ...(outputDir === undefined ? [] : ["--output-dir", outputDir]),
        ],
        { shell: false, windowsHide: true, stdio: ["pipe", "pipe", "ignore"] },
      );
    } catch {
      finish(failure("MMUU_SAVE_BRIDGE_PYTHON_UNAVAILABLE"));
      return;
    }
    child.once("error", () =>
      finish(failure("MMUU_SAVE_BRIDGE_PYTHON_UNAVAILABLE")),
    );
    child.stdin.on("error", () => {
      /* A child that exits early may close stdin. Its receipt remains authoritative. */
    });
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      outputBytes += Buffer.byteLength(chunk, "utf8");
      if (outputBytes > MAX_RECEIPT_BYTES) {
        tooLarge = true;
        child.kill();
        return;
      }
      output += chunk;
    });
    child.once("close", (exitCode, signal) => {
      if (tooLarge) {
        finish(failure("MMUU_SAVE_BRIDGE_RECEIPT_INVALID"));
        return;
      }
      if (signal) {
        finish(failure("MMUU_SAVE_BRIDGE_PROCESS_FAILED"));
        return;
      }
      try {
        finish(
          receipt(JSON.parse(output), exitCode) ??
            failure("MMUU_SAVE_BRIDGE_RECEIPT_INVALID"),
        );
      } catch {
        finish(failure("MMUU_SAVE_BRIDGE_RECEIPT_INVALID"));
      }
    });
    child.stdin.end(input, "utf8");
  });
}
