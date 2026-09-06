# Task — 配网故障定位Agent（方案D）

## Phase 1：前端 + 后端骨架 ✅

- [x] 项目目录结构创建
- [x] requirements.txt
- [x] core/__init__.py 骨架
- [x] web/app.py（FastAPI骨架，含静态文件服务）
- [x] web/static/index.html（五视图主壳）
- [x] web/static/css/style.css（暗色电力主题）
- [x] web/static/js/app.js（路由、状态）
- [x] web/static/js/topology.js（D3.js拓扑可视化）
- [x] web/static/js/api.js（后端API封装）
- [x] web/static/js/agent.js（Agent对话界面逻辑）
- [x] web/static/js/data.js（嵌入静态数据，现作为后端离线时的兜底）

## Phase 2：核心引擎接入 ✅

- [x] core/config.py
- [x] core/models.py（Pydantic）
- [x] core/data_loader.py（统一数据加载，lru_cache）
  - [x] 修复：node_loads.csv 列名不匹配导致 load_kva 恒为0（`local_load_kva`→`local_S_total_kVA`）
- [x] core/topology.py（拓扑查询）
- [x] core/fault_locator.py（修复Bug3事件分组滑动窗口）
- [x] web/routers/topology.py（API路由接入core，新增 history_fault_count 字段）
- [x] web/routers/fault.py（定位+历史事件API）
- [x] 前后端对接：故障定位、历史事件已走真实API（带本地降级）
- [x] 前后端对接：拓扑监控视图改为从 `/api/topology/{line}` 拉取真实数据（原先topology.js硬编码data.js，现已升级为"后端可用时自动替换，离线时静默回退"，与其余视图模式一致）
- [x] core/electrical_analyzer.py（用户明确要求这一版就做，见文末"电气量推理算法"详细记录）

## Phase 3：LLM Agent（后端代码已提前完成，尚未接入真实API Key验证）

- [x] agent/llm_client.py（多厂商适配：DeepSeek/Qwen/OpenAI，运行时配置优先级：设置页>.env>环境变量>默认值）
- [x] agent/tools.py（6个工具函数：query_topology / locate_fault_from_alarms / search_similar_history / get_node_info / generate_dispatch_suggestion / list_history_events）
- [x] agent/prompts.py（中文电力专业提示词）
- [x] agent/graph.py（工具调用工作流，SSE流式输出；实现为原生OpenAI function calling，非LangGraph——requirements.txt中的langgraph依赖目前未使用）
- [x] web/routers/agent.py（/api/agent/chat SSE + /api/agent/tools）
- [x] web/routers/settings.py（LLM配置保存/测试/持久化到.env）
- [x] 前后端Agent对接（agent.js已实现流式对话+工具调用可视化，非mock）
- [x] LLM Key 已配置（DeepSeek，写入 `.env`，`/api/settings/llm/test` 连接测试通过）
- [x] 抽样端到端验证通过2个场景：
  - 火龙线 18+18.25 号杆 B相短路（高置信度单分支案例）：工具调用链 locate_fault_from_alarms → search_similar_history → query_topology → generate_dispatch_suggestion 全部正确触发；定位结果（18.25→18.35，高置信度）与历史记录吻合；回答中引用的454.6kVA负荷数据来自真实拓扑而非编造；格式符合系统提示词要求（故障区段/类型/置信度/巡线建议四要素）。
  - 松坪线 66+1 号杆 AB两相短路（双分支中置信度案例）：正确识别出2个候选区段（74.3/115）都是medium，未强行给出单一答案，主动追问"74.3或115是否也报警"以进一步收窄范围，符合提示词"信息不足时主动询问"的要求；未误调用 generate_dispatch_suggestion（因故障区段未唯一确定）。
- [x] 全量回归完成（`scripts/verify_fault_regression.py`）：用新引擎（Bug3滑动窗口分组）重新处理 `data/历史数据/异常数据.xlsx` 原始数据，共分出 **15个事件**（"16条"是旧CSV按前沿点展开的行数，2024-12-10那条双前沿事件被拆成了2行；15才是真实事件数，与最初计划假设一致）。逐条比对：**15个事件的报警前沿、候选区段与旧脚本(`scripts/locate_fault.py`)100%一致**，证明Bug3修复没有改变既有正确结果。
- [x] 修复真实Bug：`core/fault_locator.py` 的 `_get_candidate_sections()` 聚合置信度逻辑——"前沿点已是末端监测点、无法再缩小范围"（该分支下游无更多监测点，最差情况）被错误归类为 medium，实际应为 low。影响15个历史事件中的**7个**（近一半）。已修复为：单一候选=high，末端死角=low，2条候选=medium，3条及以上候选=low。
- [x] 已确定置信度权威口径：以 `core/fault_locator.py` 的结构化计算为唯一标准（不再用 `core/data_loader.py` 猜测note文本子串）。`scripts/regenerate_fault_report.py` 已用该标准重新生成 `output/fault_location_report.csv`（15行，每事件一行，新增 confidence 列；旧文件已备份为 `.bak`）；`core/data_loader.py::load_history_events()` 已改为直接读取该列（保留对无该列的旧文件的子串猜测作为向下兼容兜底）。前端 `data.js` 离线兜底数据集中两条对应记录（66+1的双分支案例）confidence 同步由 low 改为 medium，保持与实时API口径一致。
- [x] 修复后端到端复核：`/api/fault/history` 现返回15条，confidence分布 高5/中3/低7；浏览器历史事件视图渲染正常，无控制台报错。

## Phase 4：产品化

- [x] 数据持久化（SQLite历史库）
  - `core/db.py`：新增 `fault_events` 表，应用启动时（`web/app.py` startup事件）建表并在表为空时从 `fault_location_report.csv` 播种15条历史事件（source='historical'）
  - `web/routers/fault.py::locate_fault_api`：每次真实定位请求（报警点非空时）追加一条新事件（source='live'），历史事件库随实际使用增长
  - `core/data_loader.py::load_history_events()` 改为直接查询DB（去掉lru_cache，因为数据会变），Agent的 `search_similar_history`/`list_history_events` 工具透明地享受这一升级，无需改动
  - 已验证：重启服务不重复播种、不丢失live事件；`/api/fault/history` 的 `source` 字段可区分历史/实时；前端历史表格新增"实时"标签+动态松坪/火龙分线路计数（此前是写死的"6次/9次"）
  - 数据库文件：`data/app.db`（新增，不在git历史里，需要在部署文档里说明）
- [x] 全链路联调（第一轮，通过真实浏览器操作而非curl逐视图验证）
  - **发现并修复严重Bug**：故障定位页面（`web/static/js/app.js::renderFaultResult`）只认本地JS兜底算法(`localFaultLocate`)的响应形状（`result.results[]`，按前沿点分组），但真实后端 `/api/fault/locate` 返回的是扁平结构（`frontier_points`+`candidate_sections`整体一份）。`api.js::apiFaultLocate` 之前把后端响应原样透传，从未做形状转换——导致**故障定位页面这个核心功能，只要连着真实后端，点"开始定位"必然显示"未找到有效的报警前沿节点"这个假失败**，此前所有验证都是通过curl直接测API或走Agent的独立工具调用路径，从未通过这个页面本身真正端到端点过，所以一直没暴露。已在 `api.js` 新增 `normalizeBackendFaultResult()` 把后端扁平结构转换成前端期望的分组结构，修复后用浏览器实测单候选/死角/双前沿/双分支四种场景全部正确渲染（含"分析摘要""定位结果"卡片、置信度进度条、候选区段小拓扑图）。
  - 顺带修复：Agent对话页"可用工具"列表是写死的HTML（含一个从未实现的`analyze_electrical_data`，缺一个真实存在的`list_history_events`），改为启动1.2s后从 `/api/agent/tools` 拉取真实列表覆盖静态占位（`agent.js::loadAvailableTools`）
  - 已验证：Agent对话页真实发送消息→SSE流式渲染→工具调用气泡+侧栏日志，浏览器里操作正常（此前只用curl测过）
- [x] 全链路联调（第二轮，交叉导航流程）
  - **发现并修复Bug**：`app.js::navTo('fault')` 内部无条件调用 `onFaultLineChange()`，而后者会 `clearAlarms()`。凡是"先填报警标签、再调用navTo('fault')跳转展示"的流程，标签填完立刻被清空——**历史事件表的"复现"按钮、拓扑图的"添加为报警点"，这两个功能此前完全失效**（能跳转到故障定位页，但报警点是空的，也不会自动出定位结果）。根因是 `onFaultLineChange()` 混合了两个语义：用户手动切换线路下拉框（该清空旧标签）vs 单纯导航到该视图做初始化（不该清空）。修复：`navTo('fault')` 内部改为只刷新快捷选择列表，不再连带清空标签；`onFaultLineChange()` 本身保持不变，继续供下拉框 onchange 使用。已用浏览器实测复现事件#7（火龙线18/18.25）和从拓扑图选中27.3.88号杆两条路径，标签正确保留、定位结果正确自动渲染。
  - **顺手修复小文案bug**：`agent.js::askAgentForFault` 拼接的提示词里出现"18号杆、18.25号杆 号杆"（多余的"号杆"重复），因为标签文本本身已带"号杆"后缀。已修复，验证输出正确。
  - 已验证：从故障定位结果点击"向Agent详细分析"→跳转Agent页→自动发送→真实拿到结构化分析（含配变负荷、外力破坏排查项、安全注意事项、预计巡查范围），全链路一次跑通。
- [x] 修复"LLM 未连接"误报（用户反馈：Key配置正确、Agent对话也正常工作，但顶部一直显示未连接）
  - 根因是两个叠加的bug：① `app.js` 页面加载时判断连接状态只看浏览器 `localStorage`，但 `apiSaveLLMConfig` 在后端可用时把配置直接存到后端、从不写 `localStorage`——通过网页"系统设置"保存（最常见路径）后刷新页面，状态永远读不到。② 即便去问后端，`GET /api/settings/llm` 原来只看进程内存里的 `_llm_config`，这个变量每次服务重启都会清空，而 `.env` 里持久化的Key其实一直有效（Agent能正常工作正是因为 `agent/llm_client.py` 有更完整的fallback逻辑），所以重启后这个接口会误报"未配置"。
  - 修复：`agent/llm_client.py` 把内部的配置解析函数 `_resolve_config` 提升为公开的 `resolve_config`；`web/routers/settings.py::get_llm_config()` 改为复用它，和 Agent 实际使用的判断逻辑保持一致；`api.js` 新增 `apiGetLLMConfig()`；`app.js` 页面加载时改为真正查询后端而不是看本地缓存。已重启服务（模拟内存态清空的真实场景）+ 浏览器实测，状态正确显示"DeepSeek 已连接"。
- [x] 登录功能（用户要求）
  - 单账号登录，账号密码 `admin`/`admin`，明文存在 `.env`（`ADMIN_USERNAME`/`ADMIN_PASSWORD`），和现有LLM Key的存法一致——demo/内网场景挡门用，不是生产级方案，正式对外前应换成更强的密码
  - `web/routers/auth.py`：登录后签发32字节随机token（`secrets.token_urlsafe`），服务端内存态记录有效token+24小时过期时间，不用JWT/数据库，风格上和 `settings.py` 的 `_llm_config` 一致（进程重启即失效，重新登录一次即可）
  - `web/app.py` 新增中间件 `auth_guard`，保护所有页面和API（不只是前端摆个登录页当门面——否则打开开发者工具直接调接口就绕过了）；白名单只放行登录本身、健康检查、`/static/`静态资源
  - 新增 `web/static/login.html`，复用主应用的 `.input`/`.btn`样式和配色，视觉风格一致
  - 主应用顶部新增"退出登录"按钮（`app.js::logout()`）
  - 已验证完整闭环：未登录访问首页重定向到登录页、未登录调API返回401、错误密码报错、正确登录后可访问、退出后session失效再次被拒绝；额外验证了Agent的SSE流式对话（用fetch而非普通请求，容易被登录改动误伤）在登录态下依然正常
- [x] 侧边栏折叠功能——做了两版后用户决定去掉，最终状态：
  - 折叠交互整体移除（`toggleSidebar()`、`restoreSidebarState()`、`#sidebar.collapsed`一套CSS规则、面包屑条里的折叠按钮全部删掉），侧边栏恢复固定宽度常驻展开
  - **保留**面包屑条 `#breadcrumb-bar`（"首页 › 当前页面名"），随 `navTo()` 动态更新（`VIEW_LABELS`映射）——这是用户独立要求的路由提示，与折叠功能是两回事，没有一起撤销
  - 移除侧边栏内的4个分组标签"监控/分析/数据/系统"（用户要求，与折叠功能无关，予以保留）
- [x] 修复历史事件搜索框被浏览器自动填充"admin"（用户反馈）：根因是该input没有设置`autocomplete`，浏览器的表单启发式把它和登录用户名关联了起来。顺手排查了页面上所有类似风险的input（报警杆号输入框、LLM Key/Base URL、算法参数、数据路径），统一加上`autocomplete="off"`；3个API Key输入框（`type="password"`）用的是`autocomplete="new-password"`而不是`off`——Chrome对password字段的`off`经常不生效，`new-password`是让浏览器不弹已保存密码建议的标准做法。
- [x] 新增"第三方/自定义"LLM提供商配置 + 获取模型列表功能（用户要求）
  - 原理：几乎所有OpenAI兼容服务都实现了标准的`GET /models`端点，openai SDK的`client.models.list()`就是对它的直接封装，不需要自己拼HTTP请求
  - 后端：`agent/llm_client.py`新增`list_models(api_key, base_url)`——直接用传入的值创建临时client去试探，不经过`resolve_config()`（因为这个操作发生在用户填完表单、还没点"保存"的时候，要用输入框当前值而不是已保存配置）；`_DEFAULTS`和`resolve_config()`的if/elif都加了`"custom"`分支；`core/config.py`加`custom_api_key/base_url/model`三个字段；`web/routers/settings.py`新增`POST /api/settings/llm/models`
  - 前端：LLM提供商配置新增第4个tab"第三方 / 自定义"，Base URL输入框旁一个"获取模型列表"图标按钮（`bi-cloud-download`，拉取中显示`bi-arrow-repeat`旋转态），模型字段用`<input list>`+`<datalist>`而不是纯下拉框——既能从拉取到的列表里选，也能直接手动输入任意模型名，不受限于列表
  - 已用真实DeepSeek Key当"第三方服务"实测：成功拉取3个模型（`deepseek-v4-flash`等，注意这和现有DeepSeek tab硬编码的`deepseek-chat`/`deepseek-reasoner`选项不一样，说明官方模型列表已经更新，这个新功能能拿到最新的真实列表而不是写死的旧选项）、无效Key场景、空字段场景，以及保存配置的完整闭环，全部走通。测试产生的`.env`残留（`CUSTOM_API_KEY`、`LLM_PROVIDER`被改到custom）已经清理，恢复回用户原本的DeepSeek配置。
- [x] "获取模型列表"扩展到DeepSeek/通义千问/OpenAI三个官方provider（用户要求，避免服务商更新模型后UI还停留在写死的旧选项——实测证实了这个必要性：DeepSeek官方现在实际返回的是`deepseek-v4-flash`等，跟tab里硬编码的`deepseek-chat`/`deepseek-reasoner`完全对不上）
  - JS重构：`onCustomConfigChange`/`fetchCustomModels`泛化成`onProviderConfigChange(provider)`/`fetchModelsFor(provider)`，4个tab共用一套逻辑，不再各写一份
  - HTML：DeepSeek/Qwen/OpenAI三个面板布局统一成"Base URL+获取按钮在最上面，模型字段用input+datalist"，和"第三方"面板风格一致；模型字段保留合理默认值（如`deepseek-chat`），不点获取也能用
  - Agent对话页左下角的模型提供商下拉框同步加上"第三方 / 自定义"选项（用户反馈之前没同步，已修复；同时把LLM连接状态显示的provider标签映射也补上了`custom → 第三方`，避免顶部状态显示成英文"custom"，和其他provider的中文标签风格不一致）
  - **顺手修复一个重要的持久化bug**：`save_llm_config`此前只把`api_key`写入`.env`，`base_url`和`model`只存在进程内存里，重启就丢。DeepSeek/Qwen/OpenAI因为有硬编码默认值兜底，这个缺陷被掩盖了；但"第三方/自定义"完全没有默认base_url，一旦重启配置就直接失效。已修复为三者一起持久化。修复过程中，用户已经实际用真实的第三方中转站（`http://127.0.0.1:8317/v1`，模型`claude-opus-4-6-thinking`）保存过一次配置——为了不因为我重启服务器验证代码而弄丢这份还没被完整持久化的真实配置，重启前先读出当前运行时的完整配置，重启后立刻用修复后的逻辑重新保存了一遍，`.env`里确认已经有`CUSTOM_BASE_URL`/`CUSTOM_MODEL`两行。
  - 已用真实DeepSeek Key验证DeepSeek tab的"获取模型列表"端到端可用；Qwen/OpenAI因为没有真实key，只验证了UI结构和按钮disable/enable逻辑正确（无key时按钮应为disabled）。
- [x] LLM配置迁移到SQLite + 修复"刷新页面配置消失"（用户反馈）
  - **诊断**：真正根因不是存储介质，是"系统设置"页表单从来没有"页面加载时回填已保存配置"这一步——`.env`里数据其实一直都在（验证过重启前后文件内容不变），只是前端从没把它读回表单显示，所以看起来像丢了。
  - 用户明确要求换SQLite，这本身也是合理的架构改进（`.env`是纯文本KV、字符串拼接读写，遇到特殊字符容易出问题；项目里`core/db.py`已经有一套SQLite持久化风格，统一更好）。两件事一起做了：
    - `core/db.py`新增`llm_provider_config`表（每个provider一行）和`app_settings`表（存`active_llm_provider`）
    - `agent/llm_client.py::resolve_config()`优先级改为 运行时临时值 > **SQLite已保存配置** > .env/环境变量(仅初始引导) > 默认值
    - `web/routers/settings.py`：`save_llm_config`改写SQLite（不再写`.env`，删除了`_write_env_key`）；新增`GET /api/settings/llm/all`返回所有provider的完整明文配置供表单回填
    - **一次性迁移**：`init_db()`里仿照`fault_events`表"首次为空时播种"的模式，若`llm_provider_config`表为空则从`.env`读取现有配置导入SQLite，避免这次架构调整让用户已保存的配置"凭空消失"。迁移时发现自己引入的一个小bug——用`os.getenv("LLM_PROVIDER")`读取，但`.env`是pydantic-settings自己解析的，从不进程环境变量，`os.getenv`根本读不到；改用`settings.llm_provider`修复。
    - 前端`app.js`新增`loadAndFillLLMForms()`，在`navTo('settings')`时自动拉取所有provider配置回填表单，并自动切到当前激活的provider tab——这是真正修复用户体感问题的地方。
  - 已验证完整闭环：迁移正确执行（用户已有的deepseek+custom两组真实配置都在SQLite里）、表单在**真实进程重启后**依然正确回填（这是比"刷新页面"更严格的测试）、保存新配置正常、Agent对话用custom provider正常工作。测试过程中产生的痕迹（qwen测试记录、active_provider一度被测试切走）已清理，最终状态是用户真实的custom配置。
- [x] 退出登录从顶部右上角移到侧边栏左下角（用户要求），和LLM连接状态放在一起（`.sidebar-logout`），已验证点击后正常登出跳转到登录页。
- [x] 移除全部"南方电网"/"South Grid"字样（用户要求）：`agent/prompts.py`系统提示词、`index.html`/`login.html`的标题和副标题、`implementation_plan.md`。副标题统一改为中性的"10kV Distribution Fault Intelligence"。已实测Agent自我介绍确认不再提及公司名。
- [ ] UI动效polish（部分完成，见上面侧边栏折叠）
- [x] 部署文档（`README.md`）：环境要求、安装、LLM配置两种方式、开发/生产启动命令、必需静态数据文件清单、SQLite历史库的自动播种/重置说明、内网部署两个真实限制（LLM需联网、图标字体走CDN）、`.env.example`里`DATA_DIR`/`OUTPUT_DIR`两项当前不生效的遗留问题、目录结构、常见问题排查
- [ ] 演示准备

## 数据核实 + 电气量推理算法（用户要求，MVP阶段，误差大可接受，后续迭代）

用户原话核心诉求：①"再三仔细"核对单线图与拓扑数据，确保异常数据能对应到图上；②线路参数按南网标准处理，不确定的地方自主判断，不追问；③后端要"加上算法并参与推理预测"，误差大没关系。要求过程中不打断提问，全程自主推进。

### 数据核实结论
- 读了两份单线图PDF（`data/单线图/`）。**结论：PDF文字提取不能作为逐字核对的权威源**——真实线路极其庞大（松坪线58km/983基混凝土杆，火龙线66km/726基杆），系统只建模了44个监测点（故障指示器安装点，不是每根杆都装），这是预期内的设计；但PDF转文字对这种密集重叠标注经常漏字（这次连"27"号杆这么关键的干线节点都没提取到），逐字比对不可靠。
- 改用更可靠的方式：直接核对原始Excel（`正常数据.xlsx`10000行/48个监测点名称、`异常数据.xlsx`28行/15次事件）与`name_mapping.csv`/`nodes.csv`的映射关系。**结论：异常数据.xlsx里出现的监测点100%正确映射到松坪线/火龙线44个节点，没有遗漏**。有4个原始名称在`name_mapping.csv`里查不到（北冲线/极乐村线/邵九线各一个监测点+1个光伏并网点），核实后确认它们**只出现在正常数据里，从未出现在任何一条异常/报警记录里**——被排除在系统范围外完全正确，不是bug。
- `output/edges_with_params.csv`里的线路参数（R1约0.13-0.16欧姆/km，符合10kV配电网架空线路典型范围）经核实是合理的，不需要重新设计，implementation_plan.md早先的评估（"✅正确"）成立。

### 电气量推理算法（`core/electrical_analyzer.py`，新文件）
- **关键发现**：`异常数据.xlsx`/`正常数据.xlsx`里其实有完整的三相电压(kV)/电流(A)/相位/K值实测数据，此前所有开发（`common.py`/`build_topology.py`/`locate_fault.py`）都只用了"监测点名称+线路状态文本+时间"三个字段，这些电气量数据从未被利用过。
- 算法设计为**矩阵法的可选增强层，不是替代**：找不到对应原始记录时静默返回`matched=False`，矩阵法主结论完全不受影响。
  - 电压读数"-9.999"/原始值负数是故障指示器该相测不到有效值的哨兵值，这是判断故障相最直接的信号，比解析中文报警文本更底层，两者可以交叉验证（`consistent_with_report`字段）
  - 电流数值量级很小（0.1~30A，不像真实短路电流的几百到几千A量级），判断可能是指示器自身检测电流而非线路负荷电流，**没有用它做"电流突增"判据**，避免给出无数据支撑的结论
  - K值、温度、湿度物理含义不明确，只记录展示，不参与推理
  - 三相不平衡度、综合异常评分（0-100，启发式加权，非精确物理量）、严重程度分级（高/中/低）
  - 全部输出都诚实标注"基于历史真实数据的启发式规则分析，样本量有限（仅28条/15次事件），仅供辅助参考，不替代矩阵法主结论"
- **过程中发现并修复一个真实bug**：最初实现里，同一杆号历史上多次不相关故障的电气量记录会被一起返回、混在一次分析里（实测触发：查"18号杆事件"混入了2024-03-27和2024-12-10两次完全不同的事件）。修复：给`FaultLocateRequest`新增可选的`event_time`字段，精确匹配±60秒窗口内的记录；不提供时间时退化为"取该监测点最新一条"（更贴近"运维口头报告当下故障"的语义）。"复现历史事件"功能已同步传入事件时间，Agent工具调用场景则用默认的"取最新"。
- 集成链路：`core/fault_locator.py`（try/except包裹，任何异常都不影响主流程）→ `web/routers/fault.py`（API响应新增`electrical_analysis`字段）→ `agent/tools.py`（`locate_fault_from_alarms`工具结果附带电气量摘要）→ `agent/prompts.py`（新增使用规则，明确要求LLM谨慎表述、不夸大、不编造数据）→ 前端`app.js`（故障定位结果卡片新增"电气量分析"展示区块，无匹配数据时完全不显示，不占位）。
- 已验证：真实历史事件（火龙线2024-03-27, 18/18.25三相短路）端到端全链路——API返回正确、前端"复现"按钮正确关联到对应事件（不再混入其他事件）、浏览器截图确认UI渲染正确、Agent对话正确引用电气量数据且保留了免责声明，还结合历史案例主动发现"这是重复故障区段，建议排查长期隐患"这个有价值的洞察。

### 未做的部分（决策说明）
- **前端拓扑图3D化**：用户提到"可能需要重新构建前端显示的拓扑图/3D图"，但表述本身带不确定性（"可能"），且现有2D D3.js拓扑图已经过多轮联调验证、信息展示清晰。本轮时间optimizes在数据核实和算法开发这两项更明确、更高确定性价值的任务上，未做3D重构。如果需要，是一个独立的、量级不小的前端工程，建议后续单独讨论范围（比如是要炫酷的演示效果，还是需要3D带来的实质信息增益）。

## "27号杆"核实追问 + 自定义拓扑功能（用户回来后的新一轮需求）

### "27号杆"追问：发现并纠正了自己上一轮的一个不严谨结论
用户回来后追问"松坪线你在哪里看到了27 我怎么没看到"——现场重新验证，发现上一轮"PDF文字提取漏掉了27号杆"这个说法是错的：
- 用PyMuPDF把松坪线单线图全部1362个文字块穷举比对，含"27"的只有7处（`#28.27`/`#25.27`/几个电表编号），没有一个是独立的"#27"杆号标签；又顺着渲染出的高清图从变电站开始沿主干肉眼描了一遍（`#1→#2→#6→#7→#11→#20→#25→#28→#29...`），25和28之间确实没有27。
- 翻了`scripts/build_topology.py`才搞清真实机制：这套拓扑树**从设计上就没有解析过PDF**（脚本注释原话"不依赖单线图矢量解析"），完全是从`正常数据.xlsx`/`异常数据.xlsx`里的监测点原始命名（如`10kV松坪线#27.3大`）按点号分段解析出树形结构——点号嵌套关系（如`27→27.3`）这部分真实可信（图上确实能看到`#28.13`这类分支命名规律一致），但**不带点号的干线层编号（如"27"本身）之间的父子链，是脚本按数值大小排序猜出来的，从未真正对照过图纸**。已把这处错误更正记录在案，不让文档留一个连自己都没核实过的说法。
- 抽查发现这不是孤例：松坪线8个干线编号里2个（27、115）在图上找不到，火龙线22个里也有类似情况；深挖到火龙线"81"号杆——这个在图上找不到的编号，直接是2次真实历史报警的报警点本身，撑起了2条"high confidence"结论。已如实告知用户这个风险点，供后续针对性复核。

### 核心新功能：自定义拓扑（用户原话："系统支持上传拓扑图...我们先做简单的...上传节点/边的表"）
根子原因：现有拓扑完全靠"监测点命名规律"反推，没法保证和真实图纸一致。用户提的方案是把"拓扑结构"变成人工上传+确认的一次性录入，和"算法"解耦——这样对任意拓扑通用，不止松坪线/火龙线。本轮先做最简单的表格上传版本（用户明确说"上传节点/边的表，后续再考虑要不要做成上传图片描点的交互式版本"）。

**实现的完整链路**：
- `core/custom_topology.py`（新增）：解析node_id/label的节点CSV + from_id/to_id的边CSV（自动兼容中文Windows导出CSV常见的GBK编码）；`validate_and_build_tree()`校验成树（唯一根节点、无环、无孤立分支，报详细错误);核心是`build_monitor_view()`——把"用户上传的完整物理图（含未装监测设备的纯结构杆塔）"折叠成"只含监测点的树"，折叠时把跳过的非监测节点的length/R/X累加到对应虚拟边上，输出格式和`nodes.csv`/`edges.csv`加载出来的形状完全一致。
- `core/data_loader.py`的`get_line_nodes`/`get_line_edges`：内置线路查不到时自动尝试当成自定义拓扑id去查——这个钩子一加，`core/fault_locator.py`的矩阵法/报警前沿算法**不用改一行代码**就能直接跑在任意自定义拓扑上。
- `core/db.py`：新增`custom_topologies`/`custom_nodes`/`custom_edges`三张表（SQLite，和现有LLM配置一致的持久化风格）。
- `web/routers/custom_topology.py`（新增，挂载于`/api/custom-topology`）：上传、列表、详情（完整图，管理页用）、预览（折叠后的监测点树）、批量标记监测点、批量设置线路参数、删除。
- `web/routers/fault.py`：`/locate`的`line_code`除了内置的SP/HL，现在也接受自定义拓扑id，直接复用同一套定位逻辑。
- 前端新增`web/static/js/custom-topo.js` + "自定义拓扑"导航页：上传表单、拓扑列表、管理面板（简易D3树形预览区分监测点/结构杆塔颜色、监测点勾选表格、线路参数批量设置表格）；故障定位页的线路下拉框动态追加所有自定义拓扑，选中后可以直接复用现成的"报警点输入→定位→结果展示"整套UI，不用另外做一套。

**线路参数批量设置的一个关键设计决策**：一开始按"直接覆盖成同一个总电阻/电抗值"做，很快意识到不对——用户原话"支持相同线路批量设置参数"，真实语义是"同一种导线规格（每公里电阻电抗相同），但线段长度可能不一样"，如果直接覆盖总值，长度不同的线段会算错。改成：批量表单填"每公里"电阻/电抗，后端按每条边**各自的**长度换算总值再落库，这样同一批边即使长度不同也不会错。

**过程中发现并修复的bug**：
1. `resolve_pole()`原本不区分线路做全局模糊子串匹配，导致自定义拓扑的报警杆号（比如"#7"）会被松坪线/火龙线里恰好带相同子串的监测点名称"抢先"误匹配掉，自定义拓扑那条兜底逻辑永远走不到。修复：`resolve_pole`新增可选的`line`参数，明确知道目标线路时只在该线路/拓扑内部找，不再跨线路乱撞；`fault_locator.py`同步加固，`resolve_pole`没找到时始终再直接查一次本线路节点表兜底。
2. **环境坑**：Windows下用`uvicorn --reload`时，杀掉显示在`netstat`里的主进程后，它的多进程reload子worker会变成孤儿继续占着端口——表现为"代码明明改了、日志也显示reload了，但请求结果还是旧逻辑"，排查了好几轮才用`Get-CimInstance Win32_Process`揪出孤儿进程。后续在这台机器上调试都直接不加`--reload`跑单进程，改代码后手动整个重启。
3. 前端`app.js`/`agent.js`里两处"根据线路代码猜中文名"的地方写成了`line === 'SP' ? '松坪线' : '火龙线'`——自定义拓扑的line_code必然落入`else`分支，结果定位页显示"线路：火龙线"、"向Agent详细分析"发给LLM的提示词也说错线路名（这个更严重，会让Agent用错误的线路身份去调工具）。两处都改成了"非SP/HL时去查`TOPO_DATA`里存的真实名字"。

**已验证**：Python脚本端到端测试（上传→标记监测点→按每公里换算批量设置参数→折叠后的树结构和数值全部正确→故障定位返回正确前沿/候选区段）；浏览器里用真实按钮点击（文件上传用DataTransfer模拟，其余全是真实点击/输入）走完整个流程，包括从"自定义拓扑"页跳转到"故障定位"页并自动选中、快速选择列表正确切换、定位结果正确显示拓扑名称；松坪线/火龙线15条历史事件回归测试确认无破坏。

**这一轮没做、明确留白的部分**：Agent对话的工具schema（`agent/tools.py`）里`line`参数目前还是硬编码`enum: ["松坪线","火龙线"]`，自定义拓扑接入Agent对话（让LLM能查询/引用自定义拓扑）需要额外扩展工具schema和系统提示词，这轮判断超出"先做简单的"范围，未做。用户提到的"训练算法做仿真推理"（OpenDSS方向）也完全没开始，只做了"拓扑录入+复用现成矩阵法"这一层。

### 用真实IEEE 34节点测试馈线数据验证自定义拓扑功能
用户给了`E:\IEEE34\model\Simulink 2019b\Documents\IEEE 34 Node Test Feeder Benchmark Document.doc`，要求整理出节点/边表并上机测试。

- 这个.doc是老版Word二进制格式，用COM自动化Word提取（`win32com.client`，普通文本工具打不开）。提取后发现：文档本身只有5组Configuration阻抗矩阵（300-304，ohms/mile）和一份潮流仿真结果报告（电压/电流/损耗），**不含**标准IEEE34文档通常有的"Line Segment Data"线路长度表——所以没法只从这一份文档凑出带长度的边表。
- 从潮流结果里的"FROM NODE / TO NODE"记录反解析出了完整的36条连接关系（含两个电压调节器RG10/RG11和一个降压变压器XF10的直通路径），确认了拓扑结构。
- 顺着同一个`E:\IEEE34\`目录网深挖，发现`data\metadata\`下已经有一套现成的、质量更高的结构化数据（看起来是用户自己另一个GNN故障定位研究项目的产出）：`edge_table.csv`直接给出33条边（已把RG10/RG11/XF10折叠掉）、精确长度(米/英尺)、导线配置编号；`measurement_layout.csv`给出真实的监测点布局（`include_main=1`的5个母线：800/814/824/854/832，文档里称为"M5主测量布局"）。这比重新从Word文档手工整理更可靠，改用这套数据源，并如实告知用户这个替换决定。
- 每公里电阻/电抗：从Word文档的Configuration 300/301/302/303/304矩阵里取对角自阻抗（三相配置取三相均值，单相配置取唯一非零值），单位ohms/mile换算成ohms/km，按导线配置分组批量设置——这正好是"批量设置线路参数"功能的真实使用场景（33条边只用5组参数一次性设完，而不是34个节点、33条边逐条手填）。
- 全流程验证：上传34节点/33边 → 标记5个真实监测点 → 逐边设置真实长度 → 按5个配置分组批量设置每公里电阻/电抗 → 折叠后树形结构和累加电阻/电抗全部抽样核对正确（比如`800→814`合并了5段线路，长度31.629km，电阻电抗都是精确累加值）→ 浏览器里真实点击"用于故障定位"→模拟824+854两点同时报警（854是824的下游子孙）→ 正确识别854为唯一前沿点、给出"854→832，高置信度"结论，"故障区段示意"图正确画出800→814→824→854(前沿)→832(候选)的完整链路。
- **顺手发现并修复一个真实的前端竞态条件bug**：`fillFaultLineOptions()`（负责往故障定位页下拉框动态追加自定义拓扑选项）在"从自定义拓扑页点击'用于故障定位'"这个场景下会被连续触发两次（`navTo('fault')`内部触发一次、`ctUseForFaultLocate`又主动触发一次），两次调用交错执行导致下拉框里同一个拓扑出现两次重复选项。修复：给这个函数加了"进行中Promise"防重入锁，并发调用共享同一次执行结果，不再各自清空/各自追加。
- 这次真实规模（34节点、33边，含多层分支和不同规格导线混用）的测试，也顺带验证了"监测点折叠"算法在比之前5节点玩具用例复杂得多的真实拓扑上依然算得对——这个真实IEEE34拓扑现在留在系统里（topology_id=`ct_32be2c23`），可以直接当作演示/继续测试用。

## 通用化重构：移除松坪线/火龙线，转向完全通用架构（用户明确要求）

用户原话核心诉求：①因为要做通用agent系统，把松坪线/火龙线相关的东西**连数据一起清理**掉（用户在选项里明确选的是"连数据一起清理"，不是"代码通用化但数据先留着"）；②prompts也要改成通用的；③"上传历史数据→算法给出输出"这一步，用户选的是**做一个新的推理模型**（不是"沿用矩阵法+电气量分析就算完事"，也不是"分阶段，这轮先不做"）。

考虑到项目此前完全没有版本控制，这种规模的删改没有安全网，先执行了 `git init` + 一次快照提交作为回退点，再动手。

### 后端：彻底移除硬编码线路
- `core/config.py`：删掉 `NODES_CSV`/`EDGES_CSV`/`NAME_MAPPING_CSV`/`NODE_LOADS_CSV`/`EDGES_WITH_PARAMS_CSV`/`FAULT_REPORT_CSV`/`HISTORY_XLSX_DIR` 等一整套指向松坪线/火龙线数据文件的路径常量。
- `core/data_loader.py`：整个重写，删掉所有CSV/Excel读取逻辑（`load_nodes`/`load_edges`/`load_name_mapping`/`_read_csv`等），只保留跨拓扑查找（`get_line_nodes`/`get_line_edges`/`resolve_pole`/`load_all_monitor_nodes`）和历史事件读取，数据源统一是`core.custom_topology`+SQLite。
- `core/topology.py`：`SUPPORTED_LINES=["松坪线","火龙线"]`这个硬编码列表删掉，`get_all_topology()`改成遍历`db.list_custom_topologies()`；`get_node`/`get_node_by_pole`新增可选的`line`参数，避免不同拓扑之间碰巧id重名时全局查找误命中（这是个真实存在但此前没意识到的风险点，趁这次重构一并修了）。
- `web/routers/topology.py`：整个文件删除——它的全部功能（列表/详情/节点查询）已经被更通用的`web/routers/custom_topology.py`覆盖，留着就是死代码。
- `web/routers/fault.py`：`LINE_CODE_MAP={"SP":"松坪线","HL":"火龙线"}`删掉，`line_code`现在就是topology_id本身，不用先查表转换名称。
- `core/db.py`：`_seed_from_csv`（从`fault_location_report.csv`播种15条历史事件的逻辑）整个删掉——系统现在从空表开始，历史事件完全来自实际使用；一次性手工清理了数据库里已有的29条`line='松坪线'/'火龙线'`的`fault_events`记录（保留了自定义拓扑测试产生的记录）。
- **`core/electrical_analyzer.py`删除，替换成`core/electrical_inference.py`**——不是简单改名，是设计上的根本变化：
  - 数据源从"两个写死路径的Excel文件"变成"每个自定义拓扑各自上传的历史电气量数据"（新增SQLite表：`custom_baseline_readings`基线读数、`custom_events`+`custom_event_readings`事件快照）。
  - 监测点标识从"需要`resolve_pole`模糊匹配Excel里乱七八糟的原始命名"简化成"直接用拓扑自己的`node_id`"（因为现在数据源和拓扑是同一个人各自上传的，不需要跨系统模糊匹配了）。
  - **新增核心能力`infer_fault_from_event(topo_id, event_id)`**——这是用户要求的"新推理模型"：给一次历史事件快照，自动判断哪些监测点的电压偏离正常基准（复用原有的哨兵值判断+基准偏离度判据，这部分启发式规则本身没变），把这些点当作自动推断出的报警点，直接喂给现成的、已经验证过的矩阵法（`core.fault_locator.locate_fault`），不需要人工先手动列出报警点。技术上是"给矩阵法接上一个自动报警点探测前端"，而不是从零训练一个模型——在只有用户自己上传的、量级不定的历史数据前提下，这是比黑箱模型更诚实、更好排查问题的路线。
  - 沿用旧版本的关键设计取舍：不用电流数值做判据（量级和真实短路电流对不上）、样本量小的诚实声明、找不到数据时优雅降级不报错。
- `web/routers/custom_topology.py`新增三个接口：`POST /{id}/historical-data/upload`（基线CSV+事件CSV，各自可选）、`GET /{id}/historical-data/events`（列出已上传事件）、`POST /{id}/historical-data/events/{event_id}/infer`（跑自动推理，成功定位时也会记入历史事件库，和手动定位行为一致）。

### Agent层：prompts和工具schema通用化
- `agent/tools.py`：6处`"enum": ["松坪线","火龙线"]`全部删掉，`line`参数改成自由字符串。新增`list_topologies`工具（供LLM查询当前有哪些拓扑——这是必须的，因为LLM不可能凭空知道用户上传的拓扑叫什么id）、`infer_fault_from_event`和`list_topology_events`工具（对应新的自动推理能力）。`_get_node_info`原来的实现直接读取一个已经不存在的`load_nodes()`函数（这是重构过程中会遇到的典型断链，写完新data_loader.py后编译期就会报错，顺手改成调用`core.topology.get_node_by_pole`）。
- `agent/prompts.py`：系统提示词整个重写——删掉写死的"松坪线19个监测点+火龙线25个监测点"背景知识段落和两条线的拓扑简图（这些内容对通用系统完全没有意义，而且会误导LLM以为只有这两条线），新增一段明确要求"不知道拓扑id时必须先调用list_topologies查询，不要凭猜测或历史对话记忆调用其他工具"，新增"两种定位方式"（人工报警点 vs 自动电气量推理）的说明。

### 前端：全面通用化 + 新增历史数据上传UI
- `web/static/index.html`：删掉顶部"松坪线在运/火龙线在运"两个写死的状态灯（换成动态的"N个拓扑"）、拓扑监控页和故障定位页里写死的`<option value="SP">松坪线</option>`静态选项（现在两个下拉框都是空的，靠JS动态填充自定义拓扑列表）、历史事件页写死的线路筛选选项、Agent欢迎语/快捷问题里提到具体线路名的地方、设置页"监测线路：松坪线/火龙线"、顶部统计卡片里假的"定位准确率93%"（这个数字从来就是编的，不是真算出来的，这次直接删掉，换成有真实数据支撑的"已上传拓扑"数量）。拓扑监控页SVG区域新增"还没有任何拓扑"空状态提示+跳转按钮。
- `web/static/js/data.js`：原来预置的松坪线完整拓扑静态数据（19个节点、负荷、坐标全部写死）整个清空，只留`window.TOPO_DATA={}`/`window.HISTORY_DATA=[]`两个空占位——这个"离线兜底静态数据"的设计在通用架构下已经没有意义（自定义拓扑必须联网到后端才存在，没有"离线也能看到默认拓扑"这回事）。
- `web/static/js/api.js`：删掉`apiGetTopology`/`normalizeTopoData`（原来专门对接`/api/topology/{SP|HL}`的封装，接口已经不存在了）、删掉`localFaultLocate`（前端本地实现的矩阵法兜底，没有硬编码拓扑数据后这个兜底逻辑没有意义）；新增`apiUploadHistoricalData`/`apiListTopologyEvents`/`apiInferFaultFromEvent`三个新接口封装。
- `web/static/js/topology.js`：`switchLine`/`loadTopoFromAPI`原来对SP/HL和自定义拓扑分两条路径处理，现在统一成一条路径（全部走`apiGetCustomTopologyPreview`）；页面初始化逻辑从"写死`switchLine('SP')`"改成"查一下有没有已上传的拓扑，有就自动选中第一个，没有就显示空状态引导上传"。
- `web/static/js/custom-topo.js`：新增"历史电气量数据 → 自动推理"卡片——基线/事件两个CSV上传、已上传事件列表、"运行推理"按钮（调用新的自动推理接口，展示推断出的报警点+故障区段结果）、"在拓扑图中查看"按钮（把推理结果通过`window.setFaultSection`直接在拓扑监控页的图上高亮出来，闭环到用户原话"并在前端拓扑图中显示故障的位置"这个要求）。
- 顺手清理了好几处硬编码的"号杆"文案后缀（松坪线/火龙线的监测点确实是电线杆，但通用拓扑的监测点可能是任意母线/节点，硬加"号杆"不准确）。

### 验证
- 后端：写了完整的Python测试脚本，覆盖"上传拓扑→标记监测点→上传历史数据（基线75条+事件15条）→列出事件→自动推理→给出824/854异常点+854→832高置信度定位"全链路，以及Agent工具层（`list_topologies`/`query_topology`/`list_topology_events`/`infer_fault_from_event`）直接调用验证，全部通过。
- 前端：用真实IEEE34拓扑（`ct_32be2c23`）在浏览器里走了一遍完整UI操作——上传历史数据CSV（文件输入用DataTransfer模拟，其余全部真实点击）→ 运行推理 → 结果卡片正确显示"自动识别出的异常点：824, 854"+"854→832 high" → 点"在拓扑图中查看"→ 拓扑监控页正确高亮824(告警/amber)、854(前沿/red)、854→832这条边(红色虚线候选区段)。
- **过程中因为自己的调试方法论踩了一次坑**：用`eval`热替换`topology.js`脚本代码来绕过浏览器缓存时，新的IIFE闭包重新执行但没有重新触发`DOMContentLoaded`，导致内部的`g`（D3的svg分组选择器）变量没被重新赋值，之后调用`window.setFaultSection`时报`Cannot read properties of undefined (reading 'selectAll')`。排查后确认是测试方法本身的问题（eval热替换和真实页面生命周期不同步），不是产品代码的bug——换成真实的整页刷新后重测，功能完全正常。这个坑之前也遇到过关联的（"Browser预览工具缓存CSS/JS"），这次是同一类问题的新变种，记录下来避免下次重复踩。
- 回归确认矩阵法核心算法本身完全没有变化（只是数据来源换了），松坪线/火龙线时代验证过的算法逻辑原样保留在`core/fault_locator.py`里。

## "Line Segment Data表"追问 + 表格合并 + 拓扑监控渲染bug（用户回来后的新一轮需求）

### 发现并纠正了自己上一轮的另一个不严谨结论
用户贴出IEEE34文档里"Line Segment Data"表的截图追问"这不是节点和边表吗"——这是本轮第二次被用户当场抓到未经核实的结论（第一次是"27号杆"），现场重新彻查：

- 上一轮说文档"不含Line Segment Data线路长度表"，判断依据是`doc.Content.Text`（Word正文纯文本流）和`doc.Tables.Count==0`（Word原生表格对象）都没找到这张表——但这两个API只覆盖"正文里的普通文字"和"正文里的原生表格"，漏了两类真实存在的内容。
- 逐个排查`doc.Shapes`/`doc.InlineShapes`：找到7个浮动图形+1个嵌入对象，其中6个是`Excel.Sheet.8`类型的嵌入OLE对象（转成.docx后从`word/embeddings/*.xls`里用`xlrd`读出，是Configuration阻抗矩阵/变压器/负荷/电容器/调压器参数，不是Line Segment Data）。
- 真正的来源是`doc.Shapes(7)`——一个类型为"画布"（Canvas）的容器，本身在`Shapes`集合里只显示为一个整体，但用`shape.CanvasItems`往下钻，里面是**137个独立的矩形文本框图形**，手工拼成的一张伪表格。这种结构`Content.Text`/`Tables`/对`Shapes`的简单遍历都不会进去，纯靠Word的对象模型几乎找不到。
- 最终用`doc.ExportAsFixedFormat(..., ExportFormat=17)`把文档导成PDF，再用`pymupdf`对渲染出的PDF页面做`page.get_text()`，才把这137个矩形的文字内容按版面位置正确抽出来，重建出完整的33行Line Segment Data（Node A/Node B/Length(ft.)/Config）。
- **交叉核验**：把这样抽出来的33条记录和上一轮实际使用的`E:\IEEE34\data\metadata\edge_table.csv`逐条比对，长度和配置编号**全部完全一致**——说明系统里已经在用的数据本身没有错，错的只是"文档里到底有没有这张表"这个背景判断。已确认部署数据无需变更，但文档来源的说法需要更正：文档里其实是有这张官方表的，只是被藏在一个此前完全没考虑到的Canvas嵌套图形结构里，不是"文档缺失这张表所以借用了旁边项目的数据"，而是"这张表在文档里，只是最初两轮排查方法都不足以发现它"。

### 表格合并：边表可以直接带长度、自动反推节点
用户看着上传界面截图指出："这里设计的是表和节点是两个表。像这种（Line Segment Data）完全可以合二为一的"——确实，官方表本身就是单张"起点/终点/长度/配置"表，从来没有独立的节点表，节点表是我们这边多余的设计。改动：
- `core/custom_topology.py::parse_edges_csv`扩展：除了必须的`from_id`/`to_id`，可选识别`length_km`/`length_m`/`length_ft`/`length(ft.)`几种长度列（自动换算成km），列名也兼容官方文档的`Node A`/`Node B`风格别名。
- 新增`derive_nodes_from_edges(edges)`：没有单独节点表时，直接从边表出现过的所有`from_id`/`to_id`按首次出现顺序反推出节点列表。
- `web/routers/custom_topology.py`的`/upload`接口：`nodes_file`改成可选（`File(None)`），不传时自动调用上面的反推函数。节点表依然保留，作为"需要给节点起一个和id不同的展示名"这类场景的可选覆盖项，不是必需项。
- 前端上传表单相应调整顺序（边表在前、必填，节点表在后、标注"可选"），补充了长度列的说明文案。

### 更严重的一个bug：拓扑监控主页渲染用错了数据形状
用户贴了4张截图对比——上传界面、官方Line Segment Data表、官方的真实分支拓扑图、系统"拓扑监控"页画出来的样子——追问"这个拓扑图是这个表的，为什么你做出来显示的却是这种呢？"。系统画出来的是一条几乎笔直的5节点直线，和官方34节点、8个分支点的真实树形结构完全对不上。

- **根因**：`拓扑监控`主页的渲染数据源一直用的是`apiGetCustomTopologyPreview`——这个接口返回的是给矩阵法算法用的"监测点折叠视图"（只保留`is_monitor_point=True`的节点，中间跳过的结构杆塔被压缩进虚拟边），IEEE34这个用例5个监测点里4个几乎顺着主干排列，折叠完自然就是一条近似直线。这不是数据错了——"自定义拓扑"管理页自己的预览用的是`get_full_view`（完整物理图），一直是对的，证明底层数据从来没问题——而是**主监控页的"人看的完整拓扑图"和"算法用的折叠输入"这两种数据形状被搞混了**，是一个真实的设计缺陷，不是数据bug。
- **修复**：明确拆成两份缓存分别供不同用途使用：
  - `window.TOPO_DATA`——完整物理图（新增`normalizeCustomTopoFullAsTopoData`归一化函数），供拓扑监控主页渲染、节点详情点击查看用；结构杆塔和监测点视觉上区分（结构杆塔画成小灰点、暗色小字，点击后提示"该节点未装监测设备，不能设为报警点"）。
  - `window.TOPO_DATA_MONITOR`——折叠后的监测点简化树（原有的`normalizeCustomTopoAsTopoData`不变），供故障定位页的"快速选择"列表、定位结果的"故障区段示意"小图这类只关心监测点的场景用。
  - `topology.js`里`setFaultSection`的故障区段高亮逻辑同步改掉：原来直接拿折叠视图给的"虚拟边"当成一条边画，如果这条虚拟边背后实际横跨了好几个结构杆塔（多跳），高亮出来会只覆盖最后一小段、明显和"故障区段"的语义对不上。改成新增`computeFaultEdges()`，在完整拓扑里从每个候选点沿`parent`链一路走到对应前沿点，把沿途每一段真实物理边都收集起来再高亮，多跳的虚拟边现在会完整点亮所有真实边段。
- 用已经改成"合并表"格式重新上传的IEEE34拓扑（旧的`ct_32be2c23`删除重建为`ct_5c7769b3`，这次直接用上面纠错后的官方原始Line Segment Data，不再借用旁边项目的`edge_table.csv`，闭环"用了未经核实数据源"这个问题）验证：
  - 后端：`/api/custom-topology/{id}`完整视图返回的分支结构和官方图纸吻合（如824节点有826和828两个子节点、834节点有842和860两个子节点）；`/api/fault/locate`对824+854同时报警仍正确返回`854→832，高置信度`。
  - 浏览器实测：拓扑监控页真实渲染出34节点、8个分支点的树形结构（不再是直线）；用页面自带的报警点快捷选择走824+854定位后，跳转回拓扑监控页确认高亮的故障区段是`854→852→832`完整两段真实边（852是中间的结构杆塔，之前的实现只会点亮其中一段），和后端返回结果一致。

### 明确没有做的部分
- `scripts/`目录下30多个文件（松坪线/火龙线相关的Python脚本+一大批MATLAB/Simulink探索性脚本和模型文件）**没有删除**——这些是纯离线、不影响应用运行的历史资料，且看起来代表相当大量的前期探索工作，不在"通用agent系统"这个改动范围内贸然清理风险大于收益，留作参考。`output/`、`data/历史数据/`、`data/单线图/`下的原始数据文件同理，只是断开了代码对它们的引用，文件本身没有物理删除。
- Agent对话层的LLM实际调用（真实模型+新版通用工具schema+新版prompts）因为要连的本地反代模型响应较慢（一次真实对话可能超过60秒），最后一步"真实端到端对话验证"是以后台任务方式发起的，还未等到结果就已经完成了本次改动的其余验证——如果这条最后确认有问题会再补充说明。
