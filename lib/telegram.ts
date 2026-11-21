/** Shapes of the Telegram link endpoints; safe to import from client and server components. */
export type TelegramChat = { title: string | null; linked_at: string };
export type TelegramLinks = {
  configured: boolean;
  bot_username: string | null;
  chats: TelegramChat[];
};
export type TelegramCode = {
  code: string;
  expires_at: string;
  deep_link: string;
  group_link: string;
  bot_username: string;
};
