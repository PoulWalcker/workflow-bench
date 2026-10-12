// The pinned n8n CLI has no result-file flag. Read its one fresh database execution
// in a separate trusted process, after execute exits; diagnostics are never input.
const sqlite3 = require(require.resolve('sqlite3', {paths: ['/usr/local/lib/node_modules/n8n']}));
const {parse} = require(require.resolve('flatted', {paths: ['/usr/local/lib/node_modules/n8n']}));
const [database, workflow, limitText] = process.argv.slice(2);
const limit = Number(limitText);
const db = new sqlite3.Database(database, sqlite3.OPEN_READONLY);
db.configure('busyTimeout', 1000);
function finish(value) {
  let size = 0;
  try {
    const output = JSON.stringify(value, (key, current) => {
      // Flatted references can expand repeatedly. Stop during traversal, before
      // allocating an unbounded serialized claim or writing it to the host pipe.
      size += Buffer.byteLength(JSON.stringify(key)) + 2;
      size += current !== null && typeof current === 'object'
        ? 2 : Buffer.byteLength(JSON.stringify(current) ?? 'null');
      if (size > limit) throw new Error('result_too_large');
      return current;
    });
    process.stdout.write(output);
  } catch {
    process.stdout.write('{"error":"result_too_large"}');
  }
  db.close();
}
db.all('SELECT id, workflowId, mode, status FROM execution_entity LIMIT 2', [], (error, rows) => {
  if (error || rows.length !== 1 || rows[0].workflowId !== workflow || rows[0].mode !== 'cli') {
    finish({error: 'missing_execution'});
    return;
  }
  const execution = rows[0];
  db.get('SELECT data FROM execution_data WHERE executionId = ? AND length(CAST(data AS BLOB)) <= ?',
    [execution.id, limit], (error, row) => {
      if (error || !row) {
        finish({error: 'execution_data_unavailable'});
        return;
      }
      try {
        const result = parse(row.data).resultData;
        const items = result.lastNodeExecuted === 'BenchResult'
          ? result.runData.BenchResult.at(-1).data.main[0] : [];
        finish({execution_id: String(execution.id), workflow_id: execution.workflowId,
          status: execution.status, claim: items.length === 1 ? items[0].json : null});
      } catch {
        finish({error: 'execution_data_invalid'});
      }
    });
});
