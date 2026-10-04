from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[1]
p=(ROOT/'data/soft_test/collector_soft_test.sqlite3').resolve()
for x in [p,Path(str(p)+'-wal'),Path(str(p)+'-shm')]: x.unlink(missing_ok=True)
runtime=(ROOT/'data/soft_test/runtime').resolve()
expected_runtime=(ROOT.resolve()/'data'/'soft_test'/'runtime').resolve()
if runtime != expected_runtime or ROOT.resolve() not in runtime.parents:
    raise RuntimeError(f'Refusing to reset unexpected soft-test path: {runtime}')
if runtime.exists(): shutil.rmtree(runtime)
directories = [
    runtime/'private/screenshots', runtime/'private/staging', runtime/'private/replay_batches',
    runtime/'images/carousell', runtime/'images/mudah', runtime/'temporary',
    runtime/'exports', runtime/'reports',
]
for directory in directories:
    directory.mkdir(parents=True, exist_ok=True)
    (directory/'.gitkeep').touch()
print('Soft-test database and runtime assets reset.')
