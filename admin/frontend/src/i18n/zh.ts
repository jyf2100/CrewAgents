export interface Translations {
  // Shell
  title: string;
  headerTitle: string;
  languageSwitch: string;
  // Navigation
  navDashboard: string;
  navSettings: string;
  navWebui: string;
  // Dashboard
  dashboard: string;
  dashboardSubtitle: string;
  totalAgents: string;
  runningAgents: string;
  stoppedAgents: string;
  createAgent: string;
  searchPlaceholder: string;
  agentName: string;
  agentStatus: string;
  agentResources: string;
  agentAge: string;
  agentActions: string;
  noAgents: string;
  noAgentsDesc: string;
  // Status
  statusRunning: string;
  statusStopped: string;
  statusPending: string;
  statusUpdating: string;
  statusScaling: string;
  statusFailed: string;
  statusUnknown: string;
  // Actions
  restart: string;
  stop: string;
  start: string;
  delete: string;
  backup: string;
  cloneAgent: string;
  edit: string;
  view: string;
  save: string;
  cancel: string;
  confirm: string;
  close: string;
  refresh: string;
  back: string;
  download: string;
  upload: string;
  test: string;
  reset: string;
  // Agent Detail
  agentDetail: string;
  agentId: string;
  agentUrl: string;
  agentNamespace: string;
  agentLabels: string;
  createdAt: string;
  restartCount: string;
  // Tabs
  overview: string;
  config: string;
  logs: string;
  events: string;
  health: string;
  // Overview Tab
  podInfo: string;
  podName: string;
  podPhase: string;
  podIp: string;
  podNode: string;
  podStartedAt: string;
  containerStatus: string;
  containerReady: string;
  containerRestarts: string;
  resourceUsage: string;
  viewConfig: string;
  cpuUsage: string;
  memoryUsage: string;
  cpuRequest: string;
  cpuLimit: string;
  memoryRequest: string;
  memoryLimit: string;
  // Config Tab
  configTab: string;
  configYaml: string;
  envVariables: string;
  soulMarkdown: string;
  editConfig: string;
  editEnv: string;
  editSoul: string;
  restartAfterSave: string;
  envKey: string;
  envValue: string;
  envSecret: string;
  addEnvVar: string;
  removeEnvVar: string;
  // Logs Tab
  logsTab: string;
  logsConnecting: string;
  logsConnected: string;
  logsDisconnected: string;
  logsReconnect: string;
  logsClear: string;
  logsAutoScroll: string;
  // Events Tab
  eventsTab: string;
  eventType: string;
  eventReason: string;
  eventMessage: string;
  eventCount: string;
  eventSource: string;
  eventTime: string;
  noEvents: string;
  // Health Tab
  healthTab: string;
  healthStatus: string;
  healthLatency: string;
  healthLastCheck: string;
  healthGatewayRaw: string;
  healthCheckNow: string;
  healthOk: string;
  healthError: string;
  // Terminal Tab
  terminal: string;
  terminalConnected: string;
  terminalDisconnected: string;
  terminalConnecting: string;
  terminalReconnect: string;
  terminalDownloadPlaceholder: string;
  terminalDownloadBtn: string;
  // Create Wizard
  createTitle: string;
  createSubtitle: string;
  stepBasic: string;
  stepResources: string;
  stepLlm: string;
  stepSoul: string;
  stepReview: string;
  agentNumber: string;
  displayName: string;
  displayNamePlaceholder: string;
  llmProvider: string;
  llmApiKey: string;
  llmModel: string;
  llmBaseUrl: string;
  llmTestConnection: string;
  llmTestSuccess: string;
  llmTestFailed: string;
  soulContent: string;
  terminalEnabled: string;
  browserEnabled: string;
  streamingEnabled: string;
  memoryEnabled: string;
  sessionResetEnabled: string;
  extraEnv: string;
  // Deploy
  deploy: string;
  deploying: string;
  deploySuccess: string;
  deployFailed: string;
  deployStep: string;
  deployStatusPending: string;
  deployStatusRunning: string;
  deployStatusDone: string;
  deployStatusFailed: string;
  // Validation
  validationRequired: string;
  validationMinLength: string;
  validationInvalidNumber: string;
  validationPositiveNumber: string;
  validationAgentExists: string;
  // Settings
  settingsTitle: string;
  settingsSubtitle: string;
  adminKey: string;
  adminKeyMasked: string;
  adminKeyNew: string;
  adminKeyNewPlaceholder: string;
  changeAdminKey: string;
  defaultResources: string;
  templateManagement: string;
  templateType: string;
  templateContent: string;
  templateDeployment: string;
  templateEnv: string;
  templateConfig: string;
  templateSoul: string;
  // Login
  loginTitle: string;
  loginSubtitle: string;
  loginKeyPlaceholder: string;
  loginButton: string;
  loginFailed: string;
  loginLoading: string;
  // Errors
  errorGeneric: string;
  errorNetwork: string;
  errorUnauthorized: string;
  errorNotFound: string;
  errorServer: string;
  errorLoadFailed: string;
  errorSaveFailed: string;
  errorDeleteConfirm: string;
  errorBackupFailed: string;
  // Cluster
  clusterStatus: string;
  clusterNodes: string;
  clusterNodeName: string;
  clusterCpuCapacity: string;
  clusterMemoryCapacity: string;
  clusterCpuUsage: string;
  clusterMemoryUsage: string;
  clusterDiskTotal: string;
  clusterDiskUsed: string;
  // Time
  timeJustNow: string;
  timeMinutesAgo: string;
  timeHoursAgo: string;
  timeDaysAgo: string;
  // Misc
  loading: string;
  retry: string;
  yes: string;
  no: string;
  enabled: string;
  disabled: string;
  copy: string;
  copied: string;
  version: string;
  documentation: string;

  // API Access
  apiAccess: string;
  apiServerUrl: string;
  apiKeyMasked: string;
  testApiConnection: string;
  testApiSuccess: string;
  testApiFailed: string;
  testApiLatency: string;
  copyUrl: string;
  copyKey: string;

  // Admin-specific
  validationAdminKeyLength: string;
  keyMismatch: string;
  adminKeyChanged: string;
  applySuccess: string;
  settingsSaved: string;
  soulSaved: string;
  confirmKeyChange: string;
  confirmNewKey: string;
  confirmNewKeyPlaceholder: string;
  statusStarting: string;
  showHide: string;
  pause: string;
  resume: string;
  filterLogs: string;
  invalidCpuFormat: string;
  invalidMemoryFormat: string;
  quickStats: string;
  connectedPlatforms: string;
  dataFromHealth: string;
  replicas: string;
  platform: string;
  hide: string;
  show: string;

  // Container status
  containerNotReady: string;

  // Deploy step labels
  deployStepSecret: string;
  deployStepInitData: string;
  deployStepCreateDeployment: string;
  deployStepUpdateIngress: string;
  deployStepWaitReady: string;

  // Misc
  envVarCount: string;

  // WeChat (Weixin)
  weixinConnection: string;
  weixinNotConnected: string;
  weixinNotConnectedDesc: string;
  weixinRegister: string;
  weixinReregister: string;
  weixinUnbind: string;
  weixinUnbound: string;
  weixinUnbindConfirm: string;
  weixinAccount: string;
  weixinBoundAt: string;
  weixinGroups: string;
  weixinQRTitle: string;
  weixinScanned: string;
  weixinWaiting: string;
  weixinConnected: string;

  // API Key Reveal
  revealKey: string;
  hideKey: string;

  // Swarm
  swarmOverview: string;
  swarmAgents: string;
  swarmNoAgents: string;
  swarmHealth: string;
  swarmConnected: string;
  swarmDisconnected: string;
  swarmReconnecting: string;
  navSwarm: string;
  last5min: string;
  submitted: string;
  completed: string;
  failed: string;
  queued: string;
  load: string;
  model: string;
  latency: string;
  memory: string;
  clients: string;
  redisLabel: string;
  // Knowledge
  knowledgeTitle: string;
  knowledgeAdd: string;
  knowledgeContent: string;
  knowledgeCategory: string;
  knowledgeTags: string;
  knowledgeSearch: string;
  knowledgeNoEntries: string;
  knowledgeDeleteConfirm: string;
  // Navigation
  navTasks: string;
  navKnowledge: string;
  navCrews: string;
  // Crew
  crewTitle: string;
  crewAdd: string;
  crewEdit: string;
  crewName: string;
  crewDescription: string;
  crewAgents: string;
  crewAgentId: string;
  crewAgentCapability: string;
  crewWorkflowType: string;
  crewWorkflowSteps: string;
  crewStepId: string;
  crewStepCapability: string;
  crewStepTemplate: string;
  crewStepDependsOn: string;
  crewStepInputFrom: string;
  crewStepTimeout: string;
  crewWorkflowTimeout: string;
  crewNoCrews: string;
  crewCreateButton: string;
  crewDeleteConfirm: string;
  crewDeleteLabel: string;
  crewCancel: string;
  crewSave: string;
  crewSequential: string;
  crewParallel: string;
  crewDAG: string;
  crewExecute: string;
  crewExecuting: string;
  crewExecuteConfirm: string;
  crewExecutionStatus: string;
  crewExecutionCompleted: string;
  crewExecutionFailed: string;
  crewExecutionPending: string;
  crewExecutionRunning: string;
  crewLoadError: string;
  crewAgentOnline: string;
  crewAgentOffline: string;
  crewAgentBusy: string;
  crewAddStep: string;
  crewRemoveStep: string;
  crewAddAgent: string;
  crewRemoveAgent: string;
  crewStepTemplateHint: string;
  crewValidationCycle: string;
  crewValidationEmptySteps: string;
  crewValidationRequired: string;
  comingSoon: string;
  comingSoonDescription: string;

  // User Login
  userLogin: string;
  adminLogin: string;
  userLoginHint: string;
  apiKeyPlaceholder: string;
  loginRateLimited: string;
  invalidApiKey: string;
  logout: string;
  userMode: string;

  // Email Auth
  emailLogin: string;
  emailPlaceholder: string;
  passwordLabel: string;
  passwordPlaceholder: string;
  registerButton: string;
  registerSuccess: string;
  registerFailed: string;
  backToLogin: string;

  // User Management (admin)
  userManagement: string;
  activateUser: string;
  bindAgent: string;
  deleteUser: string;
  noUsers: string;
  userActive: string;
  userInactive: string;
  userDeleteConfirm: string;

  // WebUI Provisioning
  startChat: string;
  provisionStatus: string;
  provisionCompleted: string;
  provisionPending: string;
  provisionFailed: string;
  provisionNotStarted: string;
  provisionSkipped: string;
  registerSuccessWaitActivation: string;

  // Orchestrator
  orchestratorNav: string;
  orchestratorOverview: string;
  orchestratorNewTask: string;
  orchestratorTaskList: string;
  orchestratorAgentFleet: string;
  orchestratorNoAgents: string;
  orchestratorNoTasks: string;
  orchestratorStatusOnline: string;
  orchestratorStatusDegraded: string;
  orchestratorStatusOffline: string;
  orchestratorCircuitClosed: string;
  orchestratorCircuitOpen: string;
  orchestratorCircuitHalfOpen: string;
  orchestratorSubmitTask: string;
  orchestratorPromptLabel: string;
  orchestratorInstructionsLabel: string;
  orchestratorPriorityLabel: string;
  orchestratorTimeoutLabel: string;
  orchestratorCallbackLabel: string;
  orchestratorSubmitting: string;
  orchestratorSubmitSuccess: string;
  orchestratorSubmitError: string;
  orchestratorTaskStatus: string;
  orchestratorTaskAgent: string;
  orchestratorTaskCreated: string;
  orchestratorTaskDuration: string;
  orchestratorTaskTokens: string;
  orchestratorTaskResult: string;
  orchestratorTaskError: string;
  orchestratorTaskRetries: string;
  orchestratorCancelTask: string;
  orchestratorCircuitBreaker: string;
  orchestratorLoad: string;
  orchestratorHealthCheck: string;
  orchestratorCurrentLoad: string;
  orchestratorMaxConcurrent: string;

  // Orchestrator Routing
  requiredTags: string;
  requiredTagsHint: string;
  routingInfo: string;
  routingStrategy: string;
  matchedTags: string;
  fallback: string;
  candidateScores: string;
  role: string;
  tags: string;
  orchestratorAgentRole: string;
  orchestratorAgentTags: string;
  routingShadowInfo: string;
  routingNoMatch: string;

  // Orchestrator detail / overview shared
  taskNotFound: string;
  runId: string;
  routingReason: string;
  agent: string;
  orchestratorActiveTasks: string;
  orchestratorDoneCount: string;
  orchestratorCircuit: string;
  orchestratorLoadFailed: string;
  orchestratorCancelFailed: string;
  promptPlaceholder: string;
  instructionsPlaceholder: string;
  tokens: string;
  duration: string;
  score: string;
  selectedCount: string;

  // Agent Metadata
  agentRole: string;
  agentTags: string;
  tagInputPlaceholder: string;
  saveMetadata: string;
  metadataSaved: string;
  roleCoder: string;
  roleAnalyst: string;
  roleGeneralist: string;
  editMetadata: string;
  metadataDesc: string;

  // Domain + Skills
  domainLabel: string;
  domainGeneralist: string;
  domainCode: string;
  domainCodeDesc: string;
  domainData: string;
  domainDataDesc: string;
  domainOps: string;
  domainOpsDesc: string;
  domainCreative: string;
  domainCreativeDesc: string;
  installedSkills: string;
  noInstalledSkills: string;
  skillTags: string;
  skillTagsRoutingHint: string;
  freeTags: string;
  freeTagsHint: string;
  orchestratorAgentDomain: string;
  orchestratorSkillCount: string;
  preferredTags: string;
  preferredTagsHint: string;
  skillTagsPlaceholder: string;
  // File Browser
  fileBrowser: string;
  fileBrowserTitle: string;
  filePath: string;
  fileName: string;
  fileSize: string;
  fileType: string;
  fileEmpty: string;
  fileNotFound: string;
  fileLoading: string;
  filePreview: string;
  fileDownload: string;
  fileParentDir: string;
  fileDirUp: string;
  fileGoTo: string;
  fileGo: string;
  fileNoPod: string;
  fileNoPodDesc: string;
  fileBinary: string;
  fileTooLarge: string;
  fileDefaultPath: string;
  fileItemSingle: string;
  fileItemPlural: string;
  fileDownloading: string;

  // File Upload/Delete
  fileUpload: string;
  fileUploadSuccess: string;
  fileUploadError: string;
  fileUploadTooLarge: string;
  fileDelete: string;
  fileDeleteConfirm: string;
  fileDeleteSuccess: string;
  fileDeleteError: string;
  fileUploadOnlySkills: string;

  // Agent Resources Edit
  resourceEdit: string;
  resourceViewTitle: string;
  resourceEditTitle: string;
  resourceCpuRequest: string;
  resourceCpuLimit: string;
  resourceMemRequest: string;
  resourceMemLimit: string;
  resourceSave: string;
  resourceSaving: string;
  resourceSuccess: string;
  resourceError: string;
  resourceLoadError: string;
  resourceRestartNote: string;
}

export const zh: Translations = {
  // Shell
  title: "Hermes Agent 管理面板",
  headerTitle: "Hermes Agent Manager",
  languageSwitch: "English",

  // Navigation
  navDashboard: "仪表盘",
  navSettings: "设置",
  navWebui: "Web 对话",

  // Dashboard
  dashboard: "仪表盘",
  dashboardSubtitle: "管理和监控您的 Hermes Agent 实例",
  totalAgents: "总实例数",
  runningAgents: "运行中",
  stoppedAgents: "已停止",
  createAgent: "创建 Agent",
  searchPlaceholder: "搜索 Agent...",
  agentName: "名称",
  agentStatus: "状态",
  agentResources: "资源",
  agentAge: "运行时间",
  agentActions: "操作",
  noAgents: "暂无 Agent 实例",
  noAgentsDesc: "点击上方按钮创建您的第一个 Agent",

  // Status
  statusRunning: "运行中",
  statusStopped: "已停止",
  statusPending: "启动中",
  statusUpdating: "更新中",
  statusScaling: "扩缩容中",
  statusFailed: "失败",
  statusUnknown: "未知",

  // Actions
  restart: "重启",
  stop: "停止",
  start: "启动",
  delete: "删除",
  backup: "备份",
  cloneAgent: "复制",
  edit: "编辑",
  view: "查看",
  save: "保存",
  cancel: "取消",
  confirm: "确认",
  close: "关闭",
  refresh: "刷新",
  back: "返回",
  download: "下载",
  upload: "上传",
  test: "测试",
  reset: "重置",

  // Agent Detail
  agentDetail: "Agent 详情",
  agentId: "Agent 编号",
  agentUrl: "访问地址",
  agentNamespace: "命名空间",
  agentLabels: "标签",
  createdAt: "创建时间",
  restartCount: "重启次数",

  // Tabs
  overview: "概览",
  config: "配置",
  logs: "日志",
  events: "K8s Events",
  health: "健康",

  // Overview Tab
  podInfo: "Pod 信息",
  podName: "Pod 名称",
  podPhase: "阶段",
  podIp: "IP 地址",
  podNode: "节点",
  podStartedAt: "启动时间",
  containerStatus: "容器状态",
  containerReady: "就绪",
  containerRestarts: "重启次数",
  resourceUsage: "资源使用",
  viewConfig: "查看配置",
  cpuUsage: "CPU 使用",
  memoryUsage: "内存使用",
  cpuRequest: "CPU 请求",
  cpuLimit: "CPU 限制",
  memoryRequest: "内存请求",
  memoryLimit: "内存限制",

  // Config Tab
  configTab: "配置文件",
  configYaml: "Config YAML",
  envVariables: "环境变量",
  soulMarkdown: "SOUL.md",
  editConfig: "编辑配置",
  editEnv: "编辑环境变量",
  editSoul: "编辑 SOUL.md",
  restartAfterSave: "保存后重启",
  envKey: "变量名",
  envValue: "值",
  envSecret: "密钥",
  addEnvVar: "添加环境变量",
  removeEnvVar: "移除",

  // Logs Tab
  logsTab: "日志",
  logsConnecting: "正在连接日志流...",
  logsConnected: "已连接",
  logsDisconnected: "已断开",
  logsReconnect: "重新连接",
  logsClear: "清空",
  logsAutoScroll: "自动滚动",

  // Events Tab
  eventsTab: "K8s 事件",
  eventType: "类型",
  eventReason: "原因",
  eventMessage: "消息",
  eventCount: "次数",
  eventSource: "来源",
  eventTime: "时间",
  noEvents: "暂无事件",

  // Health Tab
  healthTab: "健康检查",
  healthStatus: "状态",
  healthLatency: "延迟",
  healthLastCheck: "上次检查",
  healthGatewayRaw: "网关原始响应",
  healthCheckNow: "立即检查",
  healthOk: "正常",
  healthError: "异常",

  // Terminal Tab
  terminal: "终端",
  terminalConnected: "已连接",
  terminalDisconnected: "已断开",
  terminalConnecting: "连接中...",
  terminalReconnect: "重新连接",
  terminalDownloadPlaceholder: "/文件/路径",
  terminalDownloadBtn: "下载",

  // Create Wizard
  createTitle: "创建新 Agent",
  createSubtitle: "部署一个新的 Hermes Agent 实例",
  stepBasic: "基本信息",
  stepResources: "资源配置",
  stepLlm: "LLM 配置",
  stepSoul: "SOUL.md",
  stepReview: "确认部署",
  agentNumber: "Agent 编号",
  displayName: "显示名称",
  displayNamePlaceholder: "可选，便于识别的名称",
  llmProvider: "LLM 提供商",
  llmApiKey: "API 密钥",
  llmModel: "模型",
  llmBaseUrl: "Base URL（可选）",
  llmTestConnection: "测试连接",
  llmTestSuccess: "连接成功",
  llmTestFailed: "连接失败",
  soulContent: "SOUL.md 内容",
  terminalEnabled: "启用终端",
  browserEnabled: "启用浏览器",
  streamingEnabled: "启用流式输出",
  memoryEnabled: "启用记忆",
  sessionResetEnabled: "启用会话重置",
  extraEnv: "额外环境变量",

  // Deploy
  deploy: "部署",
  deploying: "正在部署...",
  deploySuccess: "部署成功",
  deployFailed: "部署失败",
  deployStep: "步骤",
  deployStatusPending: "等待中",
  deployStatusRunning: "执行中",
  deployStatusDone: "完成",
  deployStatusFailed: "失败",

  // Validation
  validationRequired: "此项为必填",
  validationMinLength: "最少 {min} 个字符",
  validationInvalidNumber: "请输入有效的数字",
  validationPositiveNumber: "请输入正整数",
  validationAgentExists: "该编号的 Agent 已存在",

  // Settings
  settingsTitle: "系统设置",
  settingsSubtitle: "管理面板配置",
  adminKey: "管理员密钥",
  adminKeyMasked: "当前密钥（已隐藏）",
  adminKeyNew: "新密钥",
  adminKeyNewPlaceholder: "输入新的管理员密钥（至少8位）",
  changeAdminKey: "更改密钥",
  defaultResources: "默认资源配置",
  templateManagement: "模板管理",
  templateType: "模板类型",
  templateContent: "模板内容",
  templateDeployment: "Deployment 模板",
  templateEnv: "环境变量模板",
  templateConfig: "Config 模板",
  templateSoul: "SOUL.md 模板",

  // Login
  loginTitle: "管理员登录",
  loginSubtitle: "输入管理员密钥以访问 Hermes 管理面板",
  loginKeyPlaceholder: "请输入管理员密钥",
  loginButton: "登录",
  loginFailed: "密钥无效，请重试",
  loginLoading: "正在验证...",

  // Errors
  errorGeneric: "操作失败，请稍后重试",
  errorNetwork: "网络错误，请检查连接",
  errorUnauthorized: "认证失败，请重新登录",
  errorNotFound: "请求的资源不存在",
  errorServer: "服务器内部错误",
  errorLoadFailed: "加载失败",
  errorSaveFailed: "保存失败",
  errorDeleteConfirm: "确定要删除此 Agent 吗？此操作不可撤销。",
  errorBackupFailed: "备份失败",

  // Cluster
  clusterStatus: "集群状态",
  clusterNodes: "节点",
  clusterNodeName: "节点名称",
  clusterCpuCapacity: "CPU 容量",
  clusterMemoryCapacity: "内存容量",
  clusterCpuUsage: "CPU 使用率",
  clusterMemoryUsage: "内存使用率",
  clusterDiskTotal: "磁盘总量",
  clusterDiskUsed: "磁盘使用量",

  // Time
  timeJustNow: "刚刚",
  timeMinutesAgo: "{n} 分钟前",
  timeHoursAgo: "{n} 小时前",
  timeDaysAgo: "{n} 天前",

  // Misc
  loading: "加载中...",
  retry: "重试",
  yes: "是",
  no: "否",
  enabled: "已启用",
  disabled: "已禁用",
  copy: "复制",
  copied: "已复制",
  version: "版本",
  documentation: "文档",

  // API Access
  apiAccess: "API 访问",
  apiServerUrl: "API 地址",
  apiKeyMasked: "API 密钥",
  testApiConnection: "测试连接",
  testApiSuccess: "连接成功",
  testApiFailed: "连接失败",
  testApiLatency: "延迟: {n}ms",
  copyUrl: "复制地址",
  copyKey: "复制密钥",

  // Admin-specific
  validationAdminKeyLength: "密钥至少需要8个字符",
  keyMismatch: "两次输入的密钥不一致",
  adminKeyChanged: "Admin Key 已更改，请使用新密钥重新登录",
  applySuccess: "配置已应用，代理将重启",
  settingsSaved: "默认资源配置已保存",
  soulSaved: "SOUL.md 已保存",
  confirmKeyChange: "更改 Admin Key 后需要使用新密钥重新验证。确定继续？",
  confirmNewKey: "确认新密钥",
  confirmNewKeyPlaceholder: "再次输入新密钥",
  statusStarting: "启动中",
  showHide: "显示/隐藏",
  pause: "暂停",
  resume: "继续",
  filterLogs: "过滤日志...",
  invalidCpuFormat: "CPU 格式无效 (例如 1000m)",
  invalidMemoryFormat: "内存格式无效 (例如 512Mi, 1Gi)",
  quickStats: "快速统计",
  connectedPlatforms: "已连接平台",
  dataFromHealth: "来自 /health 的数据",
  replicas: "副本",
  platform: "平台",
  hide: "隐藏",
  show: "显示",

  // Container status
  containerNotReady: "未就绪",

  // Deploy step labels
  deployStepSecret: "创建 Secret",
  deployStepInitData: "初始化数据",
  deployStepCreateDeployment: "创建 Deployment",
  deployStepUpdateIngress: "更新 Ingress",
  deployStepWaitReady: "等待就绪",

  // Misc
  envVarCount: "{n} 个变量",

  // WeChat (Weixin)
  weixinConnection: "微信连接",
  weixinNotConnected: "未连接",
  weixinNotConnectedDesc: "尚未连接微信",
  weixinRegister: "注册微信",
  weixinReregister: "重新注册",
  weixinUnbind: "解绑",
  weixinUnbound: "微信已解绑",
  weixinUnbindConfirm: "确定要解绑微信吗？Agent 将会重启。",
  weixinAccount: "账号",
  weixinBoundAt: "绑定时间",
  weixinGroups: "群组",
  weixinQRTitle: "微信扫码登录",
  weixinScanned: "已扫码",
  weixinWaiting: "等待中...",
  weixinConnected: "微信已连接！",

  // API Key Reveal
  revealKey: "查看密钥",
  hideKey: "隐藏密钥",

  // Swarm
  swarmOverview: "蜂群概览",
  swarmAgents: "蜂群 Agent",
  swarmNoAgents: "没有已注册的蜂群 Agent",
  swarmHealth: "健康状态",
  swarmConnected: "已连接",
  swarmDisconnected: "已断开",
  swarmReconnecting: "重新连接中...",
  navSwarm: "蜂群",
  last5min: "近 5 分钟",
  submitted: "已提交",
  completed: "已完成",
  failed: "失败",
  queued: "排队中",
  load: "负载",
  model: "模型",
  latency: "延迟",
  memory: "内存",
  clients: "客户端数",
  redisLabel: "Redis",
  // Knowledge
  knowledgeTitle: "知识库",
  knowledgeAdd: "添加知识",
  knowledgeContent: "内容",
  knowledgeCategory: "分类",
  knowledgeTags: "标签",
  knowledgeSearch: "搜索知识...",
  knowledgeNoEntries: "暂无知识条目",
  knowledgeDeleteConfirm: "确定删除此知识条目？",

  // Navigation
  navTasks: "任务",
  navKnowledge: "知识库",
  navCrews: "Crews",

  // Crew
  crewTitle: "Crew 管理",
  crewAdd: "创建 Crew",
  crewEdit: "编辑 Crew",
  crewName: "名称",
  crewDescription: "描述",
  crewAgents: "Agent 分配",
  crewAgentId: "Agent ID",
  crewAgentCapability: "所需能力",
  crewWorkflowType: "工作流类型",
  crewWorkflowSteps: "工作流步骤",
  crewStepId: "步骤 ID",
  crewStepCapability: "能力",
  crewStepTemplate: "任务模板",
  crewStepDependsOn: "依赖步骤",
  crewStepInputFrom: "输入映射",
  crewStepTimeout: "步骤超时(秒)",
  crewWorkflowTimeout: "工作流超时(秒)",
  crewNoCrews: "暂无 Crew",
  crewCreateButton: "创建",
  crewDeleteConfirm: "确定删除此 Crew？",
  crewDeleteLabel: "删除",
  crewCancel: "取消",
  crewSave: "保存",
  crewSequential: "顺序",
  crewParallel: "并行",
  crewDAG: "DAG",
  crewExecute: "执行",
  crewExecuting: "执行中...",
  crewExecuteConfirm: "确定执行此 Crew 的工作流？",
  crewExecutionStatus: "执行状态",
  crewExecutionCompleted: "已完成",
  crewExecutionFailed: "失败",
  crewExecutionPending: "等待中",
  crewExecutionRunning: "运行中",
  crewLoadError: "加载 Crew 列表失败",
  crewAgentOnline: "在线",
  crewAgentOffline: "离线",
  crewAgentBusy: "忙碌",
  crewAddStep: "添加步骤",
  crewRemoveStep: "移除",
  crewAddAgent: "添加 Agent",
  crewRemoveAgent: "移除",
  crewStepTemplateHint: "使用 {step_id} 引用上一步输出",
  crewValidationCycle: "工作流存在循环依赖",
  crewValidationEmptySteps: "至少需要一个步骤",
  crewValidationRequired: "此字段为必填",
  comingSoon: "即将推出",
  comingSoonDescription: "该功能正在开发中，敬请期待！",

  // User Login
  userLogin: "API Key",
  adminLogin: "管理员",
  userLoginHint: "使用你 Agent 的 API Key 登录，管理你自己的 Agent",
  apiKeyPlaceholder: "输入 API Key",
  loginRateLimited: "尝试次数过多，请稍后再试",
  invalidApiKey: "API Key 无效",
  logout: "退出登录",
  userMode: "用户模式",

  // Email Auth
  emailLogin: "邮箱",
  emailPlaceholder: "输入邮箱",
  passwordLabel: "密码",
  passwordPlaceholder: "输入密码",
  registerButton: "注册",
  registerSuccess: "注册成功，等待管理员激活",
  registerFailed: "注册失败",
  backToLogin: "返回登录",

  // User Management (admin)
  userManagement: "用户管理",
  activateUser: "激活",
  bindAgent: "绑定 Agent",
  deleteUser: "删除用户",
  noUsers: "暂无注册用户",
  userActive: "已激活",
  userInactive: "未激活",
  userDeleteConfirm: "确定删除该用户？",

  // WebUI Provisioning
  startChat: "开始对话",
  provisionStatus: "对话配置",
  provisionCompleted: "已配置",
  provisionPending: "配置中...",
  provisionFailed: "配置失败",
  provisionNotStarted: "未配置",
  provisionSkipped: "WebUI 未配置",
  registerSuccessWaitActivation: "注册成功！请等待管理员激活您的账号并分配 Agent。激活后即可使用对话功能。",

  // Orchestrator
  orchestratorNav: "编排器",
  orchestratorOverview: "概览",
  orchestratorNewTask: "提交任务",
  orchestratorTaskList: "任务列表",
  orchestratorAgentFleet: "Agent 集群",
  orchestratorNoAgents: "暂无注册 Agent",
  orchestratorNoTasks: "暂无任务",
  orchestratorStatusOnline: "在线",
  orchestratorStatusDegraded: "降级",
  orchestratorStatusOffline: "离线",
  orchestratorCircuitClosed: "正常",
  orchestratorCircuitOpen: "熔断",
  orchestratorCircuitHalfOpen: "恢复中",
  orchestratorSubmitTask: "提交任务",
  orchestratorPromptLabel: "提示词",
  orchestratorInstructionsLabel: "系统指令",
  orchestratorPriorityLabel: "优先级",
  orchestratorTimeoutLabel: "超时时间（秒）",
  orchestratorCallbackLabel: "回调地址（HTTPS）",
  orchestratorSubmitting: "提交中...",
  orchestratorSubmitSuccess: "任务提交成功",
  orchestratorSubmitError: "任务提交失败",
  orchestratorTaskStatus: "状态",
  orchestratorTaskAgent: "Agent",
  orchestratorTaskCreated: "创建时间",
  orchestratorTaskDuration: "耗时",
  orchestratorTaskTokens: "Token 用量",
  orchestratorTaskResult: "结果",
  orchestratorTaskError: "错误",
  orchestratorTaskRetries: "重试次数",
  orchestratorCancelTask: "取消任务",
  orchestratorCircuitBreaker: "熔断器",
  orchestratorLoad: "负载",
  orchestratorHealthCheck: "最近健康检查",
  orchestratorCurrentLoad: "当前负载",
  orchestratorMaxConcurrent: "最大并发",

  // Orchestrator Routing
  requiredTags: "必要标签",
  requiredTagsHint: "Agent 必须同时具备所有选中的标签",
  routingInfo: "路由信息",
  routingStrategy: "策略",
  matchedTags: "匹配标签",
  fallback: "降级路由",
  candidateScores: "候选得分",
  role: "角色",
  tags: "标签",
  orchestratorAgentRole: "角色",
  orchestratorAgentTags: "标签",
  routingShadowInfo: "Shadow 信息",
  routingNoMatch: "未匹配到可用 Agent",

  // Orchestrator detail / overview shared
  taskNotFound: "任务不存在",
  runId: "运行 ID",
  routingReason: "原因",
  agent: "Agent",
  orchestratorActiveTasks: "活跃任务",
  orchestratorDoneCount: "已完成",
  orchestratorCircuit: "熔断",
  orchestratorLoadFailed: "加载数据失败",
  orchestratorCancelFailed: "取消任务失败",
  promptPlaceholder: "输入任务提示词...",
  instructionsPlaceholder: "可选系统指令...",
  tokens: "Token",
  duration: "耗时",
  score: "得分",
  selectedCount: "{n} 已选: ",

  // Agent Metadata
  agentRole: "角色",
  agentTags: "标签",
  tagInputPlaceholder: "例如 python, tool-use",
  saveMetadata: "保存",
  metadataSaved: "标签已保存",
  roleCoder: "编码",
  roleAnalyst: "分析",
  roleGeneralist: "通用",
  editMetadata: "编辑元数据",
  metadataDesc: "描述",

  // Domain + Skills
  domainLabel: "领域",
  domainGeneralist: "通用",
  domainCode: "编码",
  domainCodeDesc: "软件开发、调试、代码审查",
  domainData: "数据",
  domainDataDesc: "数据分析、可视化、统计建模",
  domainOps: "运维",
  domainOpsDesc: "部署、监控、基础设施管理",
  domainCreative: "创意",
  domainCreativeDesc: "写作、设计、内容创作",
  installedSkills: "已安装技能",
  noInstalledSkills: "暂无已安装 Skills",
  skillTags: "技能标签",
  skillTagsRoutingHint: "用于智能路由",
  freeTags: "自定义标签",
  freeTagsHint: "用于搜索和分类",
  orchestratorAgentDomain: "领域",
  orchestratorSkillCount: "{n} 个技能",
  preferredTags: "偏好标签",
  preferredTagsHint: "用于加权路由加分（非硬约束）",
  skillTagsPlaceholder: "输入标签搜索...",

  // File Browser
  fileBrowser: "文件浏览",
  fileBrowserTitle: "Pod 文件浏览",
  filePath: "路径",
  fileName: "名称",
  fileSize: "大小",
  fileType: "类型",
  fileEmpty: "目录为空",
  fileNotFound: "文件不存在或不可读",
  fileLoading: "加载中...",
  filePreview: "文件预览",
  fileDownload: "下载",
  fileParentDir: "上级目录",
  fileDirUp: "返回上级",
  fileGoTo: "跳转到",
  fileGo: "前往",
  fileNoPod: "Agent 未运行",
  fileNoPodDesc: "文件浏览需要 Agent Pod 处于运行状态",
  fileBinary: "二进制文件，请下载查看",
  fileTooLarge: "文件过大，请下载查看",
  fileDefaultPath: "/home/user/hermes",
  fileItemSingle: "个项",
  fileItemPlural: "个项",
  fileDownloading: "下载中...",

  // File Upload/Delete
  fileUpload: "上传",
  fileUploadSuccess: "文件上传成功",
  fileUploadError: "上传失败",
  fileUploadTooLarge: "文件太大（最大 10MB）",
  fileDelete: "删除",
  fileDeleteConfirm: "确认删除此文件？",
  fileDeleteSuccess: "文件已删除",
  fileDeleteError: "删除失败",
  fileUploadOnlySkills: "仅支持在 /opt/data/skills 目录上传",

  // Agent Resources Edit
  resourceEdit: "编辑资源",
  resourceViewTitle: "资源配置",
  resourceEditTitle: "编辑 Agent 资源配置",
  resourceCpuRequest: "CPU 请求",
  resourceCpuLimit: "CPU 上限",
  resourceMemRequest: "内存请求",
  resourceMemLimit: "内存上限",
  resourceSave: "保存并重启",
  resourceSaving: "更新中...",
  resourceSuccess: "资源配置已更新，Pod 正在重启。",
  resourceError: "更新资源配置失败",
  resourceLoadError: "加载当前资源配置失败",
  resourceRestartNote: "Pod 将重启以应用新的资源配置。",
};
