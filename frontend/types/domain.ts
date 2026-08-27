/**
 * Frontend-friendly domain types.
 * Bridges between backend snake_case wire format and component-friendly camelCase.
 */

export type ConversationState =
  | 'NEW'
  | 'AI_ACTIVE'
  | 'AWAITING_APPROVAL'
  | 'HUMAN_ASSIGNED'
  | 'AI_PAUSED'
  | 'CLOSED';

export type Conversation = {
  id: string;
  contactId: string;
  state: ConversationState;
  aiEnabled: boolean;
};

export type Contact = {
  id: string;
  phone: string;
  name?: string | null;
  company?: string | null;
};

export type Tag = {
  id: string;
  name: string;
};
