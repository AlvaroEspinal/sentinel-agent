import React, { useState, useRef, useEffect, useCallback } from "react";
import { Search, MapPin, Loader2, X, Plus } from "lucide-react";
import { useStore } from "../../store/useStore";
import { searchProperties, searchPermits, createPropertyAgent, geocodeAddress } from "../../services/api";
import type { Property } from "../../types";

// ─── Property type display labels ────────────────────────────────────────────
const PROPERTY_TYPE_LABELS: Record<string, string> = {
  SINGLE_FAMILY: "SFH",
  MULTI_FAMILY: "Multi",
  CONDO: "Condo",
  TOWNHOUSE: "Town",
  LAND: "Land",
  COMMERCIAL: "Comm",
  MIXED_USE: "Mixed",
  OTHER: "Other",
};

// ─── SearchBar ───────────────────────────────────────────────────────────────
const SearchBar: React.FC = () => {
  const selectProperty = useStore((s) => s.selectProperty);
  const addTrackedListing = useStore((s) => s.addTrackedListing);

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Property[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [highlightIndex, setHighlightIndex] = useState(-1);

  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Debounced search ─────────────────────────────────────────────────────
  const performSearch = useCallback(async (q: string) => {
    if (q.trim().length < 2) {
      setResults([]);
      setIsOpen(false);
      return;
    }

    const trimmed = q.trim();
    setIsLoading(true);
    try {
      const data = await searchProperties({ q: trimmed, limit: 10 });
      let props = data.properties ?? [];

      // Fallback: search permits directly if property search returns empty
      if (props.length === 0) {
        try {
          const permitData = await searchPermits({ q: trimmed, limit: 10 });
          if (permitData.permits?.length > 0) {
            // Transform permits into property-shaped results, deduped by address
            const addressMap = new Map<string, Property>();
            for (const permit of permitData.permits) {
              const addr = permit.address?.trim();
              if (!addr) continue;
              const key = addr.toLowerCase();
              if (!addressMap.has(key)) {
                addressMap.set(key, {
                  id: `permit-${permit.id}`,
                  address: addr,
                  city: permit.town_id?.replace(/_/g, " ")?.replace(/\b\w/g, (c: string) => c.toUpperCase()) || "MA",
                  state: "MA",
                  zip_code: null,
                  normalized_address: null,
                  latitude: permit.latitude || 0,
                  longitude: permit.longitude || 0,
                  parcel_id: null,
                  property_type: "OTHER",
                  year_built: null,
                  lot_size_sqft: null,
                  living_area_sqft: null,
                  bedrooms: null,
                  bathrooms: null,
                  zoning: null,
                  tax_assessment: null,
                  last_sale_price: null,
                  last_sale_date: null,
                  estimated_value: null,
                  risk_scores: null,
                  neighborhood_scores: null,
                  data_sources: [],
                  created_at: new Date().toISOString(),
                  updated_at: new Date().toISOString(),
                  active_agents_count: 0,
                  nearby_permits_count: 1,
                  nearby_cameras_count: 0,
                });
              }
            }
            props = Array.from(addressMap.values()).slice(0, 10);
          }
        } catch {
          // Permit fallback failed silently - keep empty results
        }
      }

      // If we still have no results, geocode the raw query (Google Maps-like behavior)
      if (props.length === 0) {
        try {
          const geo = await geocodeAddress(trimmed);
          if (geo.lat && geo.lon) {
            props = [{
              id: `geo-${Date.now()}`,
              address: geo.display_name || trimmed,
              city: geo.city || "",
              state: geo.state || "",
              zip_code: geo.zip || null,
              normalized_address: null,
              latitude: geo.lat,
              longitude: geo.lon,
              parcel_id: null,
              property_type: "OTHER",
              year_built: null,
              lot_size_sqft: null,
              living_area_sqft: null,
              bedrooms: null,
              bathrooms: null,
              zoning: null,
              tax_assessment: null,
              last_sale_price: null,
              last_sale_date: null,
              estimated_value: null,
              risk_scores: null,
              neighborhood_scores: null,
              data_sources: [],
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
              active_agents_count: 0,
              nearby_permits_count: 0,
              nearby_cameras_count: 0,
            }];
          }
        } catch {
          // Geocode fallback failed silently
        }
      }

      setResults(props);
      setIsOpen(true);
      setHighlightIndex(-1);
    } catch (err) {
      console.error("[SearchBar] Search failed:", err);
      setResults([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const value = e.target.value;
      setQuery(value);

      if (debounceRef.current) clearTimeout(debounceRef.current);

      debounceRef.current = setTimeout(() => {
        performSearch(value);
      }, 300);
    },
    [performSearch]
  );

  // ── Result selection ─────────────────────────────────────────────────────
  const handleSelect = useCallback(
    (property: Property) => {
      selectProperty(property);
      setQuery(property.address);
      setIsOpen(false);
      setResults([]);
      inputRef.current?.blur();
    },
    [selectProperty]
  );

  // ── Clear input ──────────────────────────────────────────────────────────
  const handleClear = useCallback(() => {
    setQuery("");
    setResults([]);
    setIsOpen(false);
    setHighlightIndex(-1);
    inputRef.current?.focus();
  }, []);

  // ── Keyboard navigation ──────────────────────────────────────────────────
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        setIsOpen(false);
        inputRef.current?.blur();
        return;
      }

      if (!isOpen || results.length === 0) return;

      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlightIndex((prev) =>
          prev < results.length - 1 ? prev + 1 : 0
        );
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlightIndex((prev) =>
          prev > 0 ? prev - 1 : results.length - 1
        );
      } else if (e.key === "Enter") {
        e.preventDefault();
        const idx = highlightIndex >= 0 ? highlightIndex : 0;
        if (results[idx]) {
          handleSelect(results[idx]);
        }
      }
    },
    [isOpen, results, highlightIndex, handleSelect]
  );

  // ── Click outside to close ───────────────────────────────────────────────
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // ── Cleanup debounce on unmount ──────────────────────────────────────────
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  return (
    <div ref={containerRef} className="relative w-full max-w-lg z-[9999]">
      {/* ── Search input ──────────────────────────────────────────────────── */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-parcl-text-muted pointer-events-none" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          onFocus={() => {
            if (results.length > 0 && query.length >= 2) setIsOpen(true);
          }}
          placeholder="Search address, city, or permit..."
          className="bg-parcl-surface border border-parcl-border rounded-lg pl-9 pr-9 py-2 text-sm text-parcl-text placeholder-parcl-text-muted font-mono focus:border-parcl-accent focus:outline-none focus:ring-1 focus:ring-parcl-accent/50 w-full max-w-lg transition-all"
        />
        {/* Loading spinner or clear button */}
        <div className="absolute right-3 top-1/2 -translate-y-1/2">
          {isLoading ? (
            <Loader2 className="w-4 h-4 text-parcl-accent animate-spin" />
          ) : query.length > 0 ? (
            <button
              onClick={handleClear}
              className="text-parcl-text-muted hover:text-parcl-text transition-colors"
              aria-label="Clear search"
            >
              <X className="w-4 h-4" />
            </button>
          ) : null}
        </div>
      </div>

      {/* ── Dropdown results ──────────────────────────────────────────────── */}
      {isOpen && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-parcl-panel/95 backdrop-blur-lg border border-parcl-border rounded-lg shadow-tactical-lg max-h-80 overflow-y-auto z-[9999]">
          {results.length > 0 ? (
            results.map((property, idx) => (
              <div
                key={property.id}
                onClick={() => handleSelect(property)}
                onMouseEnter={() => setHighlightIndex(idx)}
                className={`px-4 py-3 cursor-pointer border-b border-parcl-border/50 last:border-0 transition-colors ${
                  idx === highlightIndex
                    ? "bg-parcl-surface"
                    : "hover:bg-parcl-surface"
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-start gap-2 min-w-0">
                    <MapPin className="w-3.5 h-3.5 text-parcl-accent mt-0.5 flex-shrink-0" />
                    <div className="min-w-0">
                      <p className="text-sm text-parcl-text truncate">
                        {property.address}
                      </p>
                      <p className="text-[10px] text-parcl-text-muted mt-0.5">
                        {[property.city, property.state, property.zip_code]
                          .filter(Boolean)
                          .join(", ")}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-1 flex-shrink-0">
                    <span className="badge-blue">
                      {PROPERTY_TYPE_LABELS[property.property_type] ??
                        property.property_type}
                    </span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        const listingId = crypto.randomUUID();
                        addTrackedListing({
                          id: listingId,
                          address: property.address,
                          city: property.city || null,
                          state: property.state || "MA",
                          latitude: property.latitude,
                          longitude: property.longitude,
                          trackingStatus: "potential",
                          addedAt: new Date().toISOString(),
                        });

                        // Auto-create monitoring agent (fire and forget)
                        createPropertyAgent({
                          entity_type: "listing",
                          entity_id: listingId,
                          agent_type: "listing",
                          name: `Monitor - ${property.address.substring(0, 30)}`,
                          config: {
                            address: property.address,
                            latitude: property.latitude,
                            longitude: property.longitude,
                            radius_km: 0.5,
                          },
                          run_interval_seconds: 3600,
                        })
                          .then(({ agent }) => {
                            useStore.getState().updateTrackedListing(listingId, {
                              agentId: agent.id,
                              trackingStatus: "active",
                            });
                          })
                          .catch((err) => {
                            console.warn("[Parcl] Auto-agent creation failed:", err);
                          });
                      }}
                      className="ml-auto p-1 rounded hover:bg-parcl-accent/20 text-parcl-text-muted hover:text-parcl-accent transition-colors flex-shrink-0"
                      title="Add to tracked listings"
                    >
                      <Plus className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            ))
          ) : query.length > 2 && !isLoading ? (
            <div className="px-4 py-6 text-center text-sm text-parcl-text-muted">
              No properties found
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
};

export default SearchBar;
