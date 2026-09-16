import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

const DESKTOP_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(import.meta.url)
const vitestRoot = path.dirname(require.resolve('vitest/package.json'))
const vitestEntry = path.join(vitestRoot, 'vitest.mjs')
const SHARD_COUNT = 4
const MAX_WORKERS = 4

for (let shard = 1; shard <= SHARD_COUNT; shard += 1) {
  const shardName = `${shard}/${SHARD_COUNT}`
  console.log(`\n===== UI shard ${shardName} (${MAX_WORKERS} workers) =====`)

  const result = spawnSync(
    process.execPath,
    [vitestEntry, 'run', '--project', 'ui', `--shard=${shardName}`, `--maxWorkers=${MAX_WORKERS}`],
    {
      cwd: DESKTOP_ROOT,
      env: process.env,
      stdio: 'inherit'
    }
  )

  if (result.error) {
    console.error(`Unable to start Vitest for shard ${shardName}: ${result.error.message}`)
    process.exit(1)
  }

  if (result.status !== 0) {
    const reason = result.signal ? `signal ${result.signal}` : `exit ${result.status}`
    console.error(`UI shard ${shardName} failed with ${reason}`)
    process.exit(result.status ?? 1)
  }
}

console.log(`\nAll ${SHARD_COUNT} UI shards passed.`)
