import React from "react";
import { Activity, MessageSquare } from "lucide-react";
import { useStore } from "../../store/useStore";
import IntelFeed from "./IntelFeed";
import ChatPanel from "./ChatPanel";
import PropertyDetails from "./PropertyDetails";

const RightPanel: React.FC = () => {
  const selectedListingId = useStore((s) => s.selectedListingId);
  const selectedProperty = useStore((s) => s.selectedProperty);
  const agentFindings = useStore((s) => s.agentFindings);
  const chatMessages = useStore((s) => s.chatMessages);

  const showPropertyDetails = !!(selectedListingId || selectedProperty);

  return (
    <div className="w-[380px] flex-shrink-0 bg-parcl-panel/95 border-l border-parcl-border flex flex-col overflow-hidden">
      {/* Top section: Property Details OR Intel Feed */}
      <div className="flex flex-col" style={{ flex: "55 1 0%" }}>
        {showPropertyDetails ? (
          <PropertyDetails listingId={selectedListingId || undefined} />
        ) : (
          <>
            <div className="px-4 py-2 text-[10px] font-semibold uppercase tracking-widest text-parcl-text-dim border-b border-parcl-border flex items-center gap-2">
              <Activity className="w-3 h-3" />
              <span>Intel Feed</span>
              {agentFindings.length > 0 && (
                <span className="ml-auto text-[9px] text-parcl-text-muted">
                  {agentFindings.length}
                </span>
              )}
            </div>
            <div className="flex-1 overflow-hidden">
              <IntelFeed />
            </div>
          </>
        )}
      </div>

      {/* Divider */}
      <div className="border-t border-parcl-border flex-shrink-0" />

      {/* Bottom section: Chat Panel */}
      <div className="flex flex-col" style={{ flex: "45 1 0%" }}>
        <div className="px-4 py-2 text-[10px] font-semibold uppercase tracking-widest text-parcl-text-dim border-b border-parcl-border flex items-center gap-2">
          <MessageSquare className="w-3 h-3" />
          <span>AI Assistant</span>
          {chatMessages.length > 0 && (
            <span className="ml-auto text-[9px] text-parcl-text-muted">
              {chatMessages.length}
            </span>
          )}
        </div>
        <div className="flex-1 overflow-hidden">
          <ChatPanel />
        </div>
      </div>
    </div>
  );
};

export default RightPanel;
