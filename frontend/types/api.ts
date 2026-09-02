/**
 * Frontend mirrors of backend Pydantic schemas.
 * Filled out as endpoints are implemented; kept thin for Phase 0.
 */

export type HealthResponse = {
  status: string;
  service: string;
  version: string;
};

export type Pagination = {
  page: number;
  pageSize: number;
  total: number;
};

export type ApiError = {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
};

/** Pagination envelope used by all paginated endpoints. */
export type Page<T> = {
  items: T[];
  page: number;
  page_size: number;
  total: number;
};

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export type AuthTokens = {
  access_token: string;
  refresh_token: string;
  token_type: string;
};

export type AuthUser = {
  id: string;
  email: string;
  role: string;
  name?: string | null;
  is_active: boolean;
  accessible_sections: string[];
};

// ---------------------------------------------------------------------------
// Conversations
// ---------------------------------------------------------------------------

export type ConversationStateWire =
  | 'NEW'
  | 'AI_ACTIVE'
  | 'AWAITING_APPROVAL'
  | 'HUMAN_ASSIGNED'
  | 'AI_PAUSED'
  | 'CLOSED';

export type ConversationContactSummary = {
  id: string;
  name?: string | null;
  phone: string;
  assigned_agent_id?: string | null;
  ai_assigned?: boolean;
};

// Slim projection of a tag for inbox row chips. Derived from TagResponse so the
// shape stays coupled to the canonical tag type (and matches TagChip's prop).
export type ConversationTagSummary = Pick<TagResponse, 'id' | 'name' | 'color'>;

export type ConversationLastMessage = {
  id: string;
  direction: 'INBOUND' | 'OUTBOUND';
  content: string;
  created_at: string;
};

export type NeedsHumanCountResponse = {
  awaiting_approval: number;
  human_assigned: number;
  total: number;
};

export type ConversationListItem = {
  id: string;
  state: ConversationStateWire;
  ai_enabled: boolean;
  locked_by?: string | null;
  lock_expires_at?: string | null;
  last_message_at?: string | null;
  unread: boolean;
  contact: ConversationContactSummary;
  last_message?: ConversationLastMessage | null;
  tags?: ConversationTagSummary[];
};

export type ConversationResponse = {
  id: string;
  contact_id: string;
  state: ConversationStateWire;
  ai_enabled: boolean;
  locked_by?: string | null;
  lock_expires_at?: string | null;
  last_message_at?: string | null;
  contact?: ConversationContactSummary | null;
  allowed_transitions?: ConversationStateWire[];
};

// ---------------------------------------------------------------------------
// Messages
// ---------------------------------------------------------------------------

export type MessageDeliveryStatus =
  | 'QUEUED'
  | 'SENT'
  | 'DELIVERED'
  | 'READ'
  | 'FAILED';

export type MediaType = 'text' | 'image' | 'video' | 'audio' | 'contact';

export type MediaAssetBrief = {
  id: string;
  media_type: MediaType | string;
  file_path: string;
  mime_type?: string | null;
  duration_seconds?: number | null;
};

export type ContextMessageBrief = {
  id: string;
  content: string;
  msg_type: MediaType | string;
};

export type MessageResponse = {
  id: string;
  conversation_id: string;
  direction: 'INBOUND' | 'OUTBOUND';
  sender_type: string;
  content: string;
  delivery_status: MessageDeliveryStatus | string;
  msg_type: MediaType | string;
  meta_message_id?: string | null;
  created_at?: string | null;
  media: MediaAssetBrief[];
  context_message_id?: string | null;
  context_message?: ContextMessageBrief | null;
  last_error?: string | null;
  error_code?: number | null;
};

export type MessageListResponse = {
  items: MessageResponse[];
  total: number;
};

export type StartConversationResponse = {
  conversation_id: string;
  message: MessageResponse;
};

// ---------------------------------------------------------------------------
// Contacts
// ---------------------------------------------------------------------------

export type ContactStatus =
  | 'active'
  | 'inactive'
  | 'blocked'
  | 'contacted'
  | 'follow_up'
  | 'interested'
  | 'not_interested';

export type ContactResponse = {
  id: string;
  phone: string;
  name?: string | null;
  company?: string | null;
  status: ContactStatus;
  notes?: string | null;
  information?: string | null;
  assigned_agent_id?: string | null;
  ai_assigned: boolean;
  revenue_attributed: number;
  estimated_ltv?: number | null;
  last_interaction_at?: string | null;
  last_contacted_at?: string | null;
  last_inbound_at?: string | null;
  conversation_count: number;
  created_at: string;
  updated_at: string;
  tags?: TagResponse[];
};

export type ContactUpdateRequest = {
  name?: string | null;
  company?: string | null;
  notes?: string | null;
  information?: string | null;
  status?: ContactStatus;
  assigned_agent_id?: string | null;
  ai_assigned?: boolean;
};

export type ContactCreateRequest = {
  phone: string;
  name?: string | null;
  company?: string | null;
  status?: ContactStatus;
  notes?: string | null;
  information?: string | null;
  assigned_agent_id?: string | null;
  ai_assigned?: boolean;
};

export type ContactImportReceipt = {
  total_rows: number;
  created: number;
  updated: number;
  skipped: number;
  errors: { row: number; phone?: string | null; error: string }[];
};

// ---------------------------------------------------------------------------
// Campaigns
// ---------------------------------------------------------------------------

export type CampaignStatus =
  | 'draft'
  | 'validating'
  | 'scheduled'
  | 'queued'
  | 'dispatching'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type CampaignType = 'immediate' | 'scheduled' | 'recurring';

export type CampaignAudienceFilter = {
  tags?: string[];
  status?: string[];
  assigned_agent_id?: string | null;
  last_interaction_after?: string | null;
  last_interaction_before?: string | null;
  contact_ids?: string[];
};

export type CampaignResponse = {
  id: string;
  template_id: string;
  name: string;
  status: CampaignStatus;
  type: CampaignType;
  scheduled_at?: string | null;
  cron_expression?: string | null;
  next_run_at?: string | null;
  last_run_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  audience_filter: CampaignAudienceFilter;
  rate_limit_per_second?: number | null;
  audience_count: number;
  sent_count: number;
  delivered_count: number;
  failed_count: number;
  response_count: number;
  validation_errors: string[];
  created_by?: string | null;
  category_id?: string | null;
  created_at: string;
  updated_at: string;
};

export type CampaignCreateRequest = {
  name: string;
  template_id: string;
  type: CampaignType;
  scheduled_at?: string | null;
  cron_expression?: string | null;
  audience_filter: CampaignAudienceFilter;
  category_id?: string | null;
};

export type CampaignCategoryResponse = {
  id: string;
  name: string;
  description?: string | null;
  color?: string | null;
  created_at: string;
};

export type CampaignCategoryWithUsage = CampaignCategoryResponse & {
  usage_count: number;
};

export type CampaignCategoryListResponse = {
  items: CampaignCategoryWithUsage[];
  total: number;
  limit: number;
  offset: number;
};

export type CampaignCategoryCreateRequest = {
  name: string;
  description?: string | null;
  color?: string | null;
};

export type CampaignCategoryUpdateRequest = Partial<CampaignCategoryCreateRequest>;

export type CampaignComplianceError = {
  code: string;
  message: string;
  details: Record<string, unknown>;
};

export type CampaignValidateResult = {
  ok: boolean;
  recipient_count: number;
  errors: CampaignComplianceError[];
};

export type CampaignReport = {
  campaign_id: string;
  status: CampaignStatus;
  audience_count: number;
  sent_count: number;
  delivered_count: number;
  failed_count: number;
  response_count: number;
  pending_count: number;
  delivery_rate: number;
  failure_rate: number;
  response_rate: number;
  started_at?: string | null;
  completed_at?: string | null;
  duration_seconds?: number | null;
  status_breakdown: Record<string, number>;
  error_breakdown: { error_message: string; count: number }[];
};

export type CampaignRecipientResponse = {
  id: string;
  campaign_id: string;
  contact_id: string;
  message_id?: string | null;
  status: string;
  sent_at?: string | null;
  delivered_at?: string | null;
  failed_at?: string | null;
  responded: boolean;
  attempt_count: number;
  error_message?: string | null;
  error_code?: number | null;
  created_at: string;
  updated_at: string;
};

// ---------------------------------------------------------------------------
// Tags / categorization
// ---------------------------------------------------------------------------

export type TagResponse = {
  id: string;
  name: string;
  description?: string | null;
  color?: string | null;
  created_at: string;
};

export type TagWithUsage = TagResponse & { usage_count: number };

export type TagListResponse = {
  items: TagWithUsage[];
  total: number;
  limit: number;
  offset: number;
};

export type TagCreateRequest = {
  name: string;
  description?: string | null;
  color?: string | null;
};

export type TagUpdateRequest = Partial<TagCreateRequest>;

export type ContactTagResponse = {
  contact_id: string;
  tag_id: string;
  approved_by?: string | null;
  approved_at?: string | null;
};

export type TagSuggestionStatus = 'pending' | 'approved' | 'rejected';

export type TagSuggestionResponse = {
  id: string;
  contact_id: string;
  tag_id: string;
  confidence?: number | null;
  reason?: string | null;
  status: TagSuggestionStatus;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  created_at: string;
};

// ---------------------------------------------------------------------------
// Analytics (admin only)
// ---------------------------------------------------------------------------

export type AnalyticsRange = 'week' | 'month' | 'quarter';

export type AnalyticsCostResponse = {
  range: string;
  start_date: string;
  end_date: string;
  ai_spend_usd: number;
  message_cost_usd: number;
  meta_cost_aed: number;
  tokens_input: number;
  tokens_output: number;
  total_cost_usd: number;
  by_day: {
    metric_date: string;
    ai_spend_usd: number;
    message_cost_usd: number;
    meta_cost_aed: number;
    tokens_input: number;
    tokens_output: number;
    total_cost_usd: number;
  }[];
};

export type AnalyticsConversionResponse = {
  range: string;
  start_date: string;
  end_date: string;
  messages_sent: number;
  messages_received: number;
  messages_delivered: number;
  messages_failed: number;
  response_rate: number;
  conversion_rate: number;
  by_day: {
    metric_date: string;
    messages_sent: number;
    messages_received: number;
    response_rate: number;
  }[];
};

export type AnalyticsAiResponse = {
  range: string;
  start_date: string;
  end_date: string;
  token_spend_usd: number;
  ai_call_count: number;
  ai_error_count: number;
  tokens_input: number;
  tokens_output: number;
  avg_latency_ms?: number | null;
  ai_handled_pct: number;
};

export type AnalyticsRoiResponse = {
  range: string;
  start_date: string;
  end_date: string;
  total_revenue_usd: number;
  total_cost_usd: number;
  overall_roi?: number | null;
  top_campaigns: {
    campaign_id: string;
    campaign_name: string;
    revenue_usd: number;
    cost_usd: number;
    roi?: number | null;
  }[];
};

export type TemplateSummaryRow = {
  template_id: string;
  template_name: string;
  campaigns_used: number;
  recipients_sent: number;
  recipients_delivered: number;
  recipients_responded: number;
  response_rate: number;
  message_cost_usd: number;
  meta_cost_aed: number;
  ai_spend_usd: number;
  tokens_input: number;
  tokens_output: number;
  total_cost_usd: number;
};

export type TemplateDailyPoint = {
  metric_date: string;
  campaigns_used: number;
  recipients_sent: number;
  recipients_delivered: number;
  recipients_responded: number;
  response_rate: number;
  message_cost_usd: number;
  meta_cost_aed: number;
  ai_spend_usd: number;
  tokens_input: number;
  tokens_output: number;
  total_cost_usd: number;
};

export type TemplateDetailResponse = {
  template_id: string;
  template_name: string;
  range: string;
  start_date: string;
  end_date: string;
  totals: TemplateSummaryRow;
  by_day: TemplateDailyPoint[];
};

export type HourlyPatternPoint = {
  hour: number;
  messages_sent: number;
  messages_received: number;
  response_rate: number;
};

export type DailyPatternPoint = {
  day_of_week: number; // 0=Monday .. 6=Sunday
  messages_sent: number;
  messages_received: number;
  response_rate: number;
};

export type ResponsivenessResponse = {
  range: string;
  start_date: string;
  end_date: string;
  by_hour: HourlyPatternPoint[];
  by_day_of_week: DailyPatternPoint[];
};

// ---------------------------------------------------------------------------
// Settings (admin only)
// ---------------------------------------------------------------------------

export type AISettingsResponse = {
  kill_switch: boolean;
  auto_send_enabled: boolean;
  test_numbers: string[];
  tag_suggestions_enabled: boolean;
  response_generation_enabled: boolean;
};

export type AISettingsUpdateRequest = Partial<AISettingsResponse>;

export type ReadOnlyModeSetting = { enabled: boolean };
export type TimezoneSetting = { tz: string };
export type BusinessHoursSetting = {
  enabled: boolean;
  start: string;
  end: string;
};
export type CampaignDailyCapSetting = { enabled: boolean; limit: number };

export type OperationalSettingsResponse = {
  read_only_mode: ReadOnlyModeSetting;
  timezone: TimezoneSetting;
  business_hours: BusinessHoursSetting;
  campaign_daily_cap: CampaignDailyCapSetting;
};

export type OperationalSettingsUpdateRequest = Partial<OperationalSettingsResponse>;

export type SettingResponse = {
  key: string;
  value: unknown;
  scope: string;
};

// ---------------------------------------------------------------------------
// Users (admin surface)
// ---------------------------------------------------------------------------

export type UserRoleWire = 'admin' | 'agent';

export type UserListItem = {
  id: string;
  email: string;
  name?: string | null;
  role: UserRoleWire;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type UsersListResponse = {
  items: UserListItem[];
  total: number;
  limit: number;
  offset: number;
};

export type UserCreateRequest = {
  email: string;
  name?: string | null;
  role: UserRoleWire;
  password: string;
};

export type UserUpdateRequest = {
  name?: string | null;
  email?: string;
  role?: UserRoleWire;
  is_active?: boolean;
};

export type PasswordResetRequest = {
  password: string;
};

export type CampaignSummaryRow = {
  campaign_id: string;
  campaign_name: string;
  template_name: string;
  recipients_sent: number;
  recipients_delivered: number;
  recipients_responded: number;
  response_rate: number;
  revenue_usd: number;
  cost_usd: number;
  meta_cost_aed: number;
  tokens_input: number;
  tokens_output: number;
  roi?: number | null;
};

export type CampaignDailyPoint = {
  metric_date: string;
  recipients_sent: number;
  recipients_delivered: number;
  recipients_responded: number;
  response_rate: number;
  revenue_usd: number;
  cost_usd: number;
  meta_cost_aed: number;
  tokens_input: number;
  tokens_output: number;
  roi?: number | null;
};

export type CampaignDetailResponse = {
  campaign_id: string;
  campaign_name: string;
  range: string;
  start_date: string;
  end_date: string;
  totals: CampaignSummaryRow;
  by_day: CampaignDailyPoint[];
};

export type BackfillRequest = {
  start_date: string;
  end_date: string;
};

export type BackfillResponse = {
  task_id: string;
  start_date: string;
  end_date: string;
};

// ---------------------------------------------------------------------------
// Users (picker shape — alias of the admin UserListItem)
// ---------------------------------------------------------------------------

export type UserResponse = UserListItem;

// ---------------------------------------------------------------------------
// Contacts — bulk actions
// ---------------------------------------------------------------------------

export type BulkUpdatePatch = {
  status?: ContactStatus;
  assigned_agent_id?: string | null;
  ai_assigned?: boolean;
};

export type BulkUpdateRequest = {
  ids: string[];
  patch: BulkUpdatePatch;
};

export type BulkDeleteRequest = {
  ids: string[];
};

export type BulkActionFailure = {
  id: string;
  error: string;
};

export type BulkActionResponse = {
  count: number;
  failed: BulkActionFailure[];
};

// ---------------------------------------------------------------------------
// Templates
// ---------------------------------------------------------------------------

export type TemplateStatus = 'pending' | 'approved' | 'rejected' | 'disabled';
export type TemplateCategory = 'marketing' | 'utility' | 'authentication';

export type TemplateResponse = {
  id: string;
  meta_template_id: string | null;
  name: string;
  status: TemplateStatus;
  category: TemplateCategory;
  language: string;
  body: string | null;
  created_at: string;
  updated_at: string;
};

export type TemplateImportResult = {
  imported: number;
  updated: number;
};

export type TemplateSubmitRequest = {
  name: string;
  category: TemplateCategory;
  language: string;
  body: string;
};

// ---------------------------------------------------------------------------
// Audit logs
// ---------------------------------------------------------------------------

export type AuditAction =
  | 'create'
  | 'update'
  | 'delete'
  | 'login'
  | 'approve'
  | 'reject'
  | 'pause_ai'
  | 'resume_ai'
  | 'assign'
  | 'launch_campaign';

export type AuditLogResponse = {
  id: string;
  actor_type: string;
  actor_id: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  before_state: Record<string, unknown> | null;
  after_state: Record<string, unknown> | null;
  created_at: string | null;
};

// ---------------------------------------------------------------------------
// Market — lead capture, search, outreach, deals
// ---------------------------------------------------------------------------

export type MarketSide = 'BUY' | 'SELL' | 'UNKNOWN';
export type MarketMessageStatus = 'ACTIVE' | 'SUPERSEDED' | 'EXPIRED';
export type DealStage =
  | 'matched'
  | 'contacted'
  | 'negotiating'
  | 'confirmed'
  | 'closed'
  | 'lost';

export type MarketMessageProductOut = {
  id: string;
  product_id: string;
  product_name?: string;
  qty: number | null;
  unit_price: number | null;
  currency: string | null;
  spec: string | null;
  condition: string | null;
  grade: string | null;
  color: string | null;
  attributes: Record<string, unknown> | null;
  confidence: number;
  resolver: string;
};

export type MarketMessageResponse = {
  id: string;
  source_type: string;
  source_id: string | null;
  sender_raw: string | null;
  contact_id: string | null;
  contact_name: string | null;
  side: string;
  raw_text: string;
  normalized_text: string;
  captured_at: string;
  expires_at: string;
  status: string;
  review_status: string;
  products: MarketMessageProductOut[];
  seen_count: number;
  source_groups: Record<string, unknown>[];
  created_at: string;
};

export type MarketSearchCard = {
  market_message_id: string;
  contact_id: string | null;
  contact_name: string | null;
  sender_raw: string | null;
  raw_text: string;
  side: string;
  captured_at: string;
  freshness_minutes: number;
  products: MarketMessageProductOut[];
  seen_count: number;
  source_groups: { source_id?: string; group_name?: string; at?: string }[];
};

export type ProductResponse = {
  id: string;
  brand: string;
  family: string | null;
  canonical_name: string;
  tier: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type ProductWithAliases = ProductResponse & {
  aliases: { id: string; product_id: string; alias: string; source: string }[];
};

export type MarketSearchResponse = {
  buy_items: MarketSearchCard[];
  sell_items: MarketSearchCard[];
  buy_total: number;
  sell_total: number;
  query_text: string;
  resolved_products: ProductResponse[];
  next_cursor: string | null;
  has_more: boolean;
};

export type SavedSearchResponse = {
  id: string;
  user_id: string;
  name: string;
  query_text: string;
  resolved_product_ids: string[] | null;
  filters: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type SavedSearchCreateRequest = {
  name: string;
  query_text: string;
  resolved_product_ids?: string[] | null;
  filters?: Record<string, unknown> | null;
};

export type SearchEventResponse = {
  id: string;
  user_id: string | null;
  query_text: string;
  resolved_product_ids: string[] | null;
  filters: Record<string, unknown> | null;
  buy_result_count: number;
  sell_result_count: number;
  executed_at: string;
};

export type OutreachSendResponse = {
  id: string;
  search_event_id: string | null;
  contact_id: string;
  market_message_id: string | null;
  template_id: string | null;
  template_name?: string | null;
  rendered_body: string | null;
  status: string;
  sent_at: string | null;
  created_at: string;
};

export type OutreachSendRequest = {
  search_event_id?: string | null;
  contact_id: string;
  market_message_id?: string | null;
  template_id: string;
};

export type OutreachBatchRequest = {
  search_event_id?: string | null;
  sends: OutreachSendRequest[];
};

export type DealResponse = {
  id: string;
  buyer_contact_id: string | null;
  seller_contact_id: string | null;
  product_id: string | null;
  product_name?: string | null;
  qty: number | null;
  target_price: number | null;
  status: string;
  origin_search_event_id: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  closed_at?: string | null;
};

export type DealCreateRequest = {
  buyer_contact_id?: string | null;
  seller_contact_id?: string | null;
  product_id?: string | null;
  qty?: number | null;
  target_price?: number | null;
  origin_search_event_id?: string | null;
};

export type DealUpdateRequest = {
  status?: string | null;
  qty?: number | null;
  target_price?: number | null;
};

export type ContactProductTagResponse = {
  contact_id: string;
  product_id: string;
  product_name: string;
  product_brand: string;
  side_buy_count: number;
  side_sell_count: number;
  observation_count: number;
  first_seen_at: string;
  last_seen_at: string;
};

export type MarketMessageIngest = {
  source_type: string;
  source_id?: string | null;
  sender_raw?: string | null;
  raw_text: string;
  captured_at: string;
  dedup_hash: string;
};

// ---------------------------------------------------------------------------
// Market — Review Queue
// ---------------------------------------------------------------------------

export type MarketReviewItem = MarketMessageResponse & {
  review_status: string;
  field_confidences?: Record<string, Record<string, number>>;
};

export type ResolutionFix = {
  product_id: string;
  attributes: Record<string, unknown> | null;
};

export type TeachEntry = {
  kind: string;
  alias: string;
  canonical: string;
};

export type ResolveRequest = {
  corrected_side: string | null;
  resolutions: ResolutionFix[];
  teach: TeachEntry[];
};

export type ReviewStats = {
  queue_depth: number;
  inflow_7d: number;
  outflow_7d: number;
  median_review_seconds: number | null;
  capacity_estimate: number | null;
};

export type ReviewQueueResponse = {
  items: MarketReviewItem[];
  next_cursor: string | null;
};

// ---------------------------------------------------------------------------
// Market — Contact Intelligence (Phase 12)
// ---------------------------------------------------------------------------

export type AttributePreferenceItem = { value: string; count: number };

export type AttributePreferences = {
  storage: AttributePreferenceItem[];
  ram: AttributePreferenceItem[];
  color: AttributePreferenceItem[];
  region: AttributePreferenceItem[];
  condition: AttributePreferenceItem[];
};

export type ProductInterestOut = {
  product_id: string;
  product_name: string;
  brand: string;
  family: string | null;
  buy_count: number;
  sell_count: number;
  observation_count: number;
  first_seen: string | null;
  last_seen: string | null;
};

export type ContactIntelligenceResponse = {
  contact_id: string;
  contact_name: string | null;
  total_messages: number;
  buy_messages: number;
  sell_messages: number;
  active_since: string | null;
  last_active: string | null;
  products: ProductInterestOut[];
  attribute_preferences: AttributePreferences;
  price_range: { min_unit_price: number | null; max_unit_price: number | null; currency: string | null };
};

export type ContactsRankedResponse = {
  contact_id: string;
  contact_name: string | null;
  message_count: number;
  buy_count: number;
  sell_count: number;
  top_products: string[];
};

// ---------------------------------------------------------------------------
// ERP — Finance
// ---------------------------------------------------------------------------

export type AccountResponse = {
  id: string;
  code: string;
  name: string;
  type: string;
  normal_side: string;
  parent_id?: string | null;
  is_control: boolean;
  is_postable: boolean;
  is_active: boolean;
  description?: string | null;
  created_at?: string | null;
};

export type JournalVoucherType =
  | 'journal_entry' | 'bank_entry' | 'cash_entry' | 'contra_entry'
  | 'credit_note' | 'debit_note' | 'write_off'
  | 'opening_entry' | 'exchange_gain_loss';

export type JournalLineRequest = {
  account_id: string;
  description?: string | null;
  dr: number;
  cr: number;
  currency_code?: string | null;
  fx_rate?: number | null;
  dr_base: number;
  cr_base: number;
  party_type?: string | null;
  party_id?: string | null;
};

export type JournalLineResponse = {
  id: string;
  account_id: string;
  description?: string | null;
  dr: number;
  cr: number;
  currency_code?: string | null;
  fx_rate?: number | null;
  dr_base: number;
  cr_base: number;
  party_type?: string | null;
  party_id?: string | null;
};

export type JournalEntryCreateRequest = {
  posting_date: string;
  description?: string | null;
  voucher_type?: string;
  lines: JournalLineRequest[];
  cheque_no?: string | null;
  cheque_date?: string | null;
  is_opening?: boolean;
  user_remark?: string | null;
};

export type JournalEntryResponse = {
  id: string;
  entry_no: string;
  posting_date: string;
  period_id?: string | null;
  voucher_type: string;
  description?: string | null;
  source_type?: string | null;
  source_id?: string | null;
  status: string;
  posted_at?: string | null;
  is_opening: boolean;
  is_system_generated: boolean;
  user_remark?: string | null;
  system_remark?: string | null;
  created_at?: string | null;
  lines: JournalLineResponse[];
};

export type TrialBalanceRow = {
  account_code: string;
  account_name: string;
  account_type: string;
  opening_dr: number;
  opening_cr: number;
  period_dr: number;
  period_cr: number;
  closing_dr: number;
  closing_cr: number;
};

export type TrialBalanceResponse = {
  as_of_date: string;
  rows: TrialBalanceRow[];
  total_dr: number;
  total_cr: number;
  difference: number;
};

export type FiscalPeriodResponse = {
  id: string;
  fiscal_year: number;
  month: number;
  start_date: string;
  end_date: string;
  status: string;
};

// AR — Receivables
export type InvoiceLineRequest = {
  item_id?: string | null;
  description: string;
  qty: number;
  unit_price: number;
};

export type InvoiceCreateRequest = {
  customer_id: string;
  posting_date: string;
  due_date: string;
  currency_code?: string;
  lines: InvoiceLineRequest[];
  remarks?: string | null;
};

export type InvoiceLineResponse = {
  id: string;
  description: string;
  qty: number;
  unit_price: number;
  line_total: number;
  tax_rate?: number | null;
  tax_amount?: number | null;
};

export type InvoiceResponse = {
  id: string;
  invoice_no: string;
  customer_id: string;
  posting_date: string;
  due_date: string;
  currency_code: string;
  subtotal: number;
  tax_total: number;
  total: number;
  status: string;
  remarks?: string | null;
  lines: InvoiceLineResponse[];
  created_at?: string | null;
};

export type PaymentCreateRequest = {
  customer_id: string;
  payment_date: string;
  amount: number;
  currency_code?: string;
  payment_method: string;
  reference?: string | null;
};

export type PaymentResponse = {
  id: string;
  payment_no: string;
  customer_id: string;
  payment_date: string;
  amount: number;
  currency_code: string;
  payment_method: string;
  reference?: string | null;
  status: string;
  created_at?: string | null;
};

export type PaymentAllocationRequest = {
  invoice_id: string;
  amount: number;
};

export type AllocationResponse = {
  id: string;
  payment_id: string;
  invoice_id: string;
  amount: number;
};

export type CreditNoteCreateRequest = {
  customer_id: string;
  invoice_id?: string | null;
  date: string;
  amount: number;
  reason: string;
  currency_code?: string;
};

export type CreditNoteResponse = {
  id: string;
  credit_note_no: string;
  customer_id: string;
  invoice_id?: string | null;
  date: string;
  amount: number;
  reason: string;
  currency_code: string;
  status: string;
  created_at?: string | null;
};

export type AgeingBucket = {
  label: string;
  count: number;
  total: number;
};

export type AgeingResponse = {
  customer_id?: string | null;
  customer_name?: string | null;
  buckets: AgeingBucket[];
  total_outstanding: number;
};

export type ContactErpSummary = {
  contact_id: string;
  outstanding_balance: number;
  total_revenue: number;
  recent_invoices: InvoiceResponse[];
};

// AP — Payables
export type BillLineRequest = {
  item_id?: string | null;
  description: string;
  qty: number;
  unit_cost: number;
};

export type BillCreateRequest = {
  supplier_id: string;
  posting_date: string;
  due_date: string;
  currency_code?: string;
  lines: BillLineRequest[];
  po_id?: string | null;
  grn_id?: string | null;
  remarks?: string | null;
};

export type BillLineResponse = {
  id: string;
  description: string;
  qty: number;
  unit_cost: number;
  line_total: number;
};

export type BillResponse = {
  id: string;
  bill_no: string;
  supplier_id: string;
  posting_date: string;
  due_date: string;
  currency_code: string;
  subtotal: number;
  tax_total: number;
  total: number;
  status: string;
  po_id?: string | null;
  grn_id?: string | null;
  remarks?: string | null;
  lines: BillLineResponse[];
  created_at?: string | null;
};

export type SupplierPaymentCreateRequest = {
  supplier_id: string;
  payment_date: string;
  amount: number;
  currency_code?: string;
  payment_method: string;
  reference?: string | null;
};

export type SupplierPaymentResponse = {
  id: string;
  payment_no: string;
  supplier_id: string;
  payment_date: string;
  amount: number;
  currency_code: string;
  payment_method: string;
  reference?: string | null;
  status: string;
  created_at?: string | null;
};

export type BillAllocationRequest = {
  bill_id: string;
  amount: number;
};

export type BillAllocationResponse = {
  id: string;
  payment_id: string;
  bill_id: string;
  amount: number;
};

export type DebitNoteCreateRequest = {
  supplier_id: string;
  bill_id?: string | null;
  date: string;
  amount: number;
  reason: string;
  currency_code?: string;
};

export type DebitNoteResponse = {
  id: string;
  debit_note_no: string;
  supplier_id: string;
  bill_id?: string | null;
  date: string;
  amount: number;
  reason: string;
  currency_code: string;
  status: string;
  created_at?: string | null;
};

// ERP — Inventory
export type ItemCreateRequest = {
  sku: string;
  name: string;
  brand?: string | null;
  model?: string | null;
  category?: string | null;
  nature: string;
  uom_code: string;
  valuation_method?: string;
  default_purchase_price?: number | null;
  default_sale_price?: number | null;
  reorder_level?: number | null;
  reorder_qty?: number | null;
  is_sales_item?: boolean;
  is_purchase_item?: boolean;
  description?: string | null;
};

export type ItemResponse = {
  id: string;
  sku: string;
  name: string;
  brand?: string | null;
  model?: string | null;
  category?: string | null;
  nature: string;
  uom_id: string;
  valuation_method: string;
  default_purchase_price?: number | null;
  default_sale_price?: number | null;
  reorder_level?: number | null;
  reorder_qty?: number | null;
  is_sales_item: boolean;
  is_purchase_item: boolean;
  is_active: boolean;
  description?: string | null;
  created_at?: string | null;
};

export type WarehouseResponse = {
  id: string;
  name: string;
  code: string;
  is_active: boolean;
};

export type StockUnitResponse = {
  id: string;
  item_id: string;
  serial_no: string;
  imei?: string | null;
  status: string;
  location_id?: string | null;
  purchase_cost?: number | null;
  item_name?: string | null;
  location_code?: string | null;
};

export type StockOnHandResponse = {
  item_id: string;
  item_name: string;
  warehouse_id?: string | null;
  location_id?: string | null;
  location_code?: string | null;
  qty: number;
  value: number;
};

export type StockValuationResponse = {
  total_value: number;
  item_count: number;
  // The serialized/bulk split of total_value.
  serialized_value: number;
  bulk_value: number;
  last_reconciled_at: string | null;
};

export type SerialLookupResponse = {
  serial_no: string;
  item_id?: string | null;
  item_name?: string | null;
  status: string;
  location?: string | null;
  lifecycle: SerialMovement[];
};

export type SerialMovement = {
  posting_date: string;
  voucher_type: string;
  voucher_id: string;
  qty_change: number;
  valuation_rate: number;
  status_after?: string | null;
};

// ERP — Procurement
export type PurchaseOrderResponse = {
  id: string;
  po_no: string;
  supplier_id: string;
  currency_code: string;
  status: string;
  order_date: string;
  expected_date?: string | null;
  remarks?: string | null;
  lines: POLineResponse[];
  created_at?: string | null;
};

export type POLineResponse = {
  id: string;
  description: string;
  qty: number;
  unit_cost: number;
  line_total: number;
};

export type GRNResponse = {
  id: string;
  grn_no: string;
  po_id?: string | null;
  warehouse_id: string;
  receipt_date: string;
  status: string;
  lines: GRNLineResponse[];
  created_at?: string | null;
};

export type GRNLineResponse = {
  id: string;
  serial_no?: string | null;
  qty_received: number;
  unit_cost: number;
  line_total: number;
};

// ERP — Fulfilment
export type SalesOrderResponse = {
  id: string;
  so_no: string;
  customer_id: string;
  currency_code: string;
  status: string;
  order_date: string;
  lines: SOLineResponse[];
  created_at?: string | null;
};

export type SOLineResponse = {
  id: string;
  description: string;
  qty: number;
  unit_price: number;
  line_total: number;
};

export type DispatchResponse = {
  id: string;
  dispatch_no: string;
  so_id?: string | null;
  dispatch_date: string;
  status: string;
  lines: DispatchLineResponse[];
  created_at?: string | null;
};

export type DispatchLineResponse = {
  id: string;
  stock_unit_id?: string | null;
  qty: number;
  unit_cost: number;
};

// ERP — Reports
export type PLReportResponse = {
  fiscal_year: number;
  revenue: number;
  cogs: number;
  gross_profit: number;
  opex: number;
  net_profit: number;
  accounts: { code: string; name: string; balance: number }[];
};

// Mirrors backend BalanceSheetResponse. `equity` already includes
// `retained_earnings`, which the API derives from the P&L accounts so the
// sheet ties without a year-end closing entry.
export type BalanceSheetResponse = {
  as_of_date: string;
  assets: number;
  liabilities: number;
  equity: number;
  retained_earnings: number;
  total_liabilities_and_equity: number;
  sections?: { label: string; accounts: { code: string; name: string; balance: number }[]; total: number }[];
};

export type MarginResponse = {
  fiscal_year: number;
  total_revenue: number;
  total_cogs: number;
  gross_margin_pct: number;
  by_product: { item_id: string; item_name: string; revenue: number; cogs: number; margin_pct: number }[];
};
