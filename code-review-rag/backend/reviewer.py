import ollama
import json
import re

class Reviewer:
    def __init__(self, model='deepseek-coder:6.7b-instruct-q4_0'):
        self.model = model
    
    def review(self, code: str, context: list, query: str = "检查潜在的空指针异常、资源泄漏、逻辑错误") -> list:
        context_text = "\n\n---\n\n".join(context) if context else "无相关上下文"
        prompt = f"""你是一个资深Python代码审查专家。请根据以下相关代码片段，审查用户提交的代码。

相关代码片段：
{context_text}

用户代码：
{code}

审查重点：{query}

请按以下JSON格式输出审查意见（只输出JSON，不要其他文字）：
{{
  "issues": [
    {{
      "line": 行号（整数）,
      "severity": "高/中/低",
      "message": "问题描述",
      "suggestion": "修改建议"
    }}
  ]
}}
"""
        response = ollama.generate(model=self.model, prompt=prompt)
        output = response['response'].strip()
        # 提取JSON部分
        json_match = re.search(r'\{.*\}', output, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                return data.get('issues', [])
            except json.JSONDecodeError:
                pass
        return []