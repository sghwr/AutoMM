# Experiment Contract

每个实验目录由 agent 或人工生成，固定放在：

```text
#Myworkfolder/<competition>/<experiment>/
```

当实验代码生成完成时，必须创建直属空文件：

```text
ACK.txt
```

推荐目录：

```text
#Myworkfolder/<competition>/<experiment>/
  ACK.txt
  experiment.yaml
  train.py 或 train.ipynb
  logs/
  outputs/
```

`experiment.yaml` 可选但推荐：

```yaml
title: baseline_lgbm
competition: competition_a
kind: python
entrypoint: train.py

kaggle:
  kernel_slug: baseline-lgbm-exp001
  is_private: true
  internet: true
  dataset_sources:
    - type: dataset
      ref: your-username/my-uploaded-dataset

runtime:
  timeout_minutes: 540

outputs:
  expected:
    - submission.csv
    - metrics.json
```

输出目录由 server 注入环境变量：

```text
WORKFLOW_RUN_ID
WORKFLOW_OUTPUT_DIR
WORKFLOW_LOG_PATH
```

脚本可通过输出如下行上报进度：

```text
WORKFLOW_PROGRESS=42
```

