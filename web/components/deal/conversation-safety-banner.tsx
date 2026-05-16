interface ConversationSafetyBannerProps {
  after: string;
}

export function ConversationSafetyBanner({
  after,
}: ConversationSafetyBannerProps) {
  return (
    <div
      className="rounded-xl border-2 border-dashed bg-green-soft/60 px-4 py-3 text-caption text-green"
      style={{ borderColor: "var(--green)" }}
    >
      {`Nothing has been sent after ${after}. The next message is waiting for your click.`}
    </div>
  );
}
