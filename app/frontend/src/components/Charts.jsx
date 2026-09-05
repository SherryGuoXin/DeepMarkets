import {
  Area,
  AreaChart,
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { money, number, percent, titleCase } from "../format";

const BLUE = "#175cd3";
const BLUE_LIGHT = "#84adff";
const GRAY = "#98a2b3";
const BLACK = "#101828";
const PALETTE = ["#175cd3", "#528bff", "#84adff", "#344054", "#667085", "#98a2b3"];

function ChartTooltip({ active, payload, label, formatter = money, formatters = {} }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip">
      <strong>{label}</strong>
      {payload.map((entry) => (
        <span key={entry.dataKey}>
          <i style={{ background: entry.color }} />
          {titleCase(entry.name)}: {(formatters[entry.dataKey] || formatter)(entry.value)}
        </span>
      ))}
    </div>
  );
}

export function ValueHistoryChart({ data, dataKey, secondaryKey, formatter = money }) {
  return (
    <div className="chart-frame">
      <ResponsiveContainer width="100%" height={300}>
        <AreaChart data={data} margin={{ top: 10, right: 12, left: 8, bottom: 0 }}>
          <defs>
            <linearGradient id="blueFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={BLUE} stopOpacity={0.24} />
              <stop offset="100%" stopColor={BLUE} stopOpacity={0.01} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#eaecf0" vertical={false} />
          <XAxis dataKey="quarter_label" tickLine={false} axisLine={false} />
          <YAxis
            tickFormatter={(value) => formatter(value)}
            tickLine={false}
            axisLine={false}
            width={72}
          />
          <Tooltip content={<ChartTooltip formatter={formatter} />} />
          <Area
            type="monotone"
            dataKey={dataKey}
            name={dataKey}
            stroke={BLUE}
            strokeWidth={2.4}
            fill="url(#blueFill)"
          />
          {secondaryKey && (
            <Line
              type="monotone"
              dataKey={secondaryKey}
              name={secondaryKey}
              stroke={BLACK}
              strokeWidth={1.8}
              dot={false}
            />
          )}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function InstitutionHistoryChart({ data, dataKey, formatter = money }) {
  return (
    <div className="chart-frame">
      <ResponsiveContainer width="100%" height={320}>
        <ComposedChart data={data} margin={{ top: 10, right: 8, left: 8, bottom: 0 }}>
          <defs>
            <linearGradient id="institutionHistoryFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={BLUE} stopOpacity={0.24} />
              <stop offset="100%" stopColor={BLUE} stopOpacity={0.01} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#eaecf0" vertical={false} />
          <XAxis dataKey="quarter_label" tickLine={false} axisLine={false} />
          <YAxis
            yAxisId="portfolio"
            tickFormatter={(value) => formatter(value)}
            tickLine={false}
            axisLine={false}
            width={72}
          />
          <YAxis
            yAxisId="activity"
            orientation="right"
            tickFormatter={number}
            tickLine={false}
            axisLine={false}
            allowDecimals={false}
            width={46}
          />
          <Tooltip
            content={(
              <ChartTooltip
                formatter={formatter}
                formatters={{ new_count: number, exited_count: number }}
              />
            )}
          />
          <Legend iconType="circle" iconSize={7} />
          <Area
            yAxisId="portfolio"
            type="monotone"
            dataKey={dataKey}
            name={dataKey}
            stroke={BLUE}
            strokeWidth={2.4}
            fill="url(#institutionHistoryFill)"
          />
          <Bar yAxisId="activity" dataKey="new_count" name="Newly reported" fill={BLACK} radius={[3, 3, 0, 0]} />
          <Bar yAxisId="activity" dataKey="exited_count" name="No longer reported" fill={GRAY} radius={[3, 3, 0, 0]} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function AllocationChart({ data }) {
  const total = data.reduce((sum, item) => sum + Number(item.value_usd || 0), 0);
  return (
    <div className="allocation">
      <div className="allocation-bar" aria-label="Asset type allocation">
        {data.map((item, index) => (
          <div
            key={item.security_type}
            style={{
              width: `${total ? (item.value_usd / total) * 100 : 0}%`,
              background: PALETTE[index % PALETTE.length],
            }}
            title={`${titleCase(item.security_type)} ${percent(item.value_usd / total)}`}
          />
        ))}
      </div>
      <div className="allocation-legend">
        {data.map((item, index) => (
          <div key={item.security_type}>
            <i style={{ background: PALETTE[index % PALETTE.length] }} />
            <span>{titleCase(item.security_type)}</span>
            <strong>{percent(total ? item.value_usd / total : 0)}</strong>
            <small>{money(item.value_usd)}</small>
          </div>
        ))}
      </div>
    </div>
  );
}

export function RelationshipChart({ data, metric }) {
  const config = {
    value: ["market_value_usd", money],
    shares: ["reported_amount", number],
    weight: ["portfolio_weight", percent],
  }[metric];
  return (
    <ValueHistoryChart data={data} dataKey={config[0]} formatter={config[1]} />
  );
}
