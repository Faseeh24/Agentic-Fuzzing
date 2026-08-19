# 优化策略提示词

## 上一轮策略

{prev_spec}

## 上一轮执行结果

{prev_summary}

## 覆盖率反馈

{coverage_feedback}

## 现有崩溃签名

{crash_sigs}

## 你的任务

根据以上信息优化策略规范。考虑：

- 如果接受率低，收紧约束条件
- 如果故意破坏未产生崩溃，增加其概率
- 如果覆盖率低，添加针对未覆盖区域的 objectives
- 如果发现崩溃，生成附近的变体输入
- 保持有效测试与破坏性测试的平衡

## 输出格式

仅输出优化后的 JSON 策略规范，结构与种子提示词相同：

```json
{
  "target": "mxmlLoadString",
  "objectives": [...],
  "constraints": [...],
  "mutations": [...]
}
```

## 规则

1. 仅输出有效 JSON，不使用 markdown 代码块
2. mutations 的 probability 总和应接近 1.0
3. 根据反馈调整权重和优先级
4. 保持至少 3 个 objectives 和 3 个 constraints
