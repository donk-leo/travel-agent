import json
import os
from flask import Flask, render_template_string, request, session
from agent import run_agent

app = Flask(__name__)
app.secret_key = os.urandom(32)

PAGE = """
<h1>旅游规划 Agent</h1>
<form method="post">
  <textarea name="query" rows="5" cols="60"
            placeholder="例如：带孩子玩一天长隆，游玩为主，少走路"
            required>{{ query|e }}</textarea>
  <br>
  <button type="submit">提交需求</button>
  <button type="submit" name="action" value="reset" formnovalidate>
    开始新需求
  </button>
</form>

{% if query %}
  <h2>收到的需求</h2>
  <p>{{ query|e }}</p>
{% endif %}

{% if intent_json %}
  <h2>提取出的旅行约束</h2>
  <pre>{{ intent_json|e }}</pre>
{% endif %}
{% if decision %}
  <details>
    <summary>查看决策摘要</summary>
    <p>下一步：{{ decision.decision|e }}</p>
    <p>理由：{{ decision.reason|e }}</p>
  </details>
{% endif %}
{% if tool_decisions %}
  <details>
    <summary>查看图谱工具选择</summary>
    {% for selection in tool_decisions %}
      <p>{% if selection.kind == 'system_adjustment' %}系统补充{% else %}模型选择{% endif %}：{{ selection.tools|join('、')|e if selection.tools else '不再查询' }}</p>
      <p>理由：{{ selection.reason|e }}</p>
    {% endfor %}
  </details>
{% endif %}
{% if message %}
  <p>{{ message|e }}</p>
{% endif %}
{% if poi_results is not none %}
  <h2>{% if poi_list_all %}图谱收录的景区地点{% else %}图谱名称匹配结果{% endif %}</h2>
  <p>结果来自已采集的图谱，可能包含餐厅、车站等地点，也可能不完整。</p>
  {% if poi_list_all %}
    {% if poi_results|length >= 10000 %}
      <p>当前显示前 10000 条记录，可能还有更多。</p>
    {% else %}
      <p>共 {{ poi_results|length }} 条记录。</p>
    {% endif %}
  {% endif %}
  {% if poi_results %}
    <ul>
      {% for poi in poi_results %}
        <li>{{ poi.name|e }}（{{ poi.scenic_area|e }}）</li>
      {% endfor %}
    </ul>
  {% else %}
    <p>没有找到匹配的地点。</p>
  {% endif %}
{% endif %}
{% if route %}
  <h2>路线顺序示意</h2>

  {% if route.validation and route.validation.valid %}
    {% set segments = route.validation.segments %}

    <p>
      {{ segments[0].from_name|e }}
      {% for segment in segments %}
        → {{ segment.to_name|e }}
      {% endfor %}
    </p>

    <p>{{ route.proposal.explanation|e }}</p>

    {% if route.proposal.uncertainties %}
      <p><strong>需要进一步确认：</strong></p>
      <ul>
        {% for item in route.proposal.uncertainties %}
          <li>{{ item|e }}</li>
        {% endfor %}
      </ul>
    {% endif %}

    <details>
      <summary>查看每段路线的图谱来源</summary>
      {% for segment in segments %}
        <p>
          {{ segment.from_name|e }} → {{ segment.to_name|e }}：
          {{ segment.source_doc_ids|join("、")|e }}
        </p>
      {% endfor %}
    </details>
  {% else %}
    <p>{{ route.message|e }}</p>
  {% endif %}
{% endif %}
{% if suggestions %}
  <h2>可能适合的建议</h2>
  {% for item in suggestions %}
    <div>
      <p>
        <strong>适用条件：</strong>
        {{ item.condition.condition_text|e }}
      </p>
      <p>
        <strong>建议：</strong>
        {{ item.condition.suggestion_text|e }}
      </p>
      <p>
        <strong>选择理由：</strong>
        {{ item.reason|e }}
      </p>

      {% if item.needs_verification %}
        <p>相关条件需要进一步核实。</p>
      {% endif %}

      <details>
        <summary>查看图谱来源</summary>
        {% for source in item.evidence %}
          <p>
            关联位置：{{ source.anchor_name|e }}；
            来源文档：{{ source.source_doc_ids|join("、")|e }}
          </p>
        {% else %}
          <p>未找到对应的图谱来源。</p>
        {% endfor %}
      </details>
      <hr>
    </div>
  {% endfor %}
{% endif %}
{% if trace_json %}
  <details>
    <summary>查看工具调用记录</summary>
    {% if trace_file %}<p>记录文件：{{ trace_file|e }}</p>{% endif %}
    <pre>{{ trace_json|e }}</pre>
  </details>
{% endif %}
{% if error %}
  <h2>处理失败</h2>
  <p>{{ error|e }}</p>
{% endif %}
"""


@app.route("/", methods=["GET", "POST"])
def home():
    result = {
        "query": "", "intent": None, "decision": None,
        "tool_decisions": [], "suggestions": [], "route": None,
        "poi_results": None, "poi_list_all": False,
        "message": "", "error": "", "trace_file": "", "trace_json": ""
    }

    if request.method == "POST":
        if request.form.get("action") == "reset":
            session.pop("pending_query", None)
            result["message"] = "已开始新需求。"
        else:
            new_query = request.form.get("query", "").strip()
            previous = session.get("pending_query", "")
            if previous and new_query.startswith(previous):
                query = new_query
            elif previous:
                query = previous + "\n" + new_query
            else:
                query = new_query

            if query:
                result = run_agent(query)
                if result["needs_followup"]:
                    session["pending_query"] = query
                else:
                    session.pop("pending_query", None)

    return render_template_string(
        PAGE,
        query=result["query"],
        intent_json=json.dumps(result["intent"], ensure_ascii=False, indent=2)
        if result["intent"] is not None else "",
        decision=result["decision"],
        tool_decisions=result["tool_decisions"],
        suggestions=result["suggestions"],
        route=result["route"],
        poi_results=result["poi_results"],
        poi_list_all=result["poi_list_all"],
        message=result["message"],
        error=result["error"],
        trace_file=result["trace_file"],
        trace_json=result["trace_json"]
    )


if __name__ == "__main__":
    app.run(debug=True)
