import { Progress, Row, Col, Tag } from "antd";
import { CheckCircleFilled, CloseCircleFilled, ClockCircleFilled } from "@ant-design/icons";
import { formatPct, formatUsd } from "../utils/format";
import { sessionTitle, sessionTone } from "../utils/status";

function StatusIcon({ runStatus }) {
  if (runStatus === "FAILED") return <CloseCircleFilled />;
  if (runStatus === "COMPLETED") return <CheckCircleFilled />;
  return <ClockCircleFilled spin={runStatus === "RUNNING" || runStatus === "PENDING"} />;
}

export default function StatusCard({ runStatus, latestWarning, summary, roi, winRate, progressPercent }) {
  const tone = sessionTone(runStatus);

  return (
    <section className="status-card">
      <div className={`status-card-inner ${tone}`}>
        <Row gutter={[16, 8]} align="middle">
          <Col xs={24} lg={13} className="status-left">
            <div className={`status-title ${tone}`}>
              <StatusIcon runStatus={runStatus} />
              <span>{sessionTitle(runStatus)}</span>
            </div>
            <div className="status-message">
              {latestWarning}
              <Tag color="default">Learn more</Tag>
            </div>
          </Col>
          <Col xs={24} lg={11} className="status-right">
            <Row gutter={[12, 8]}>
              <Col span={8} className="kpi-divider">
                <div className="kpi-label">PnL</div>
                <div className="kpi-value">{formatUsd(summary.total_realized_pnl_usdc)}</div>
              </Col>
              <Col span={8} className="kpi-divider">
                <div className="kpi-label">ROI</div>
                <div className="kpi-value">{formatPct(roi)}</div>
              </Col>
              <Col span={8}>
                <div className="kpi-label">Win Rate</div>
                <div className="kpi-value">{formatPct(winRate)}</div>
              </Col>
            </Row>
            <Progress percent={progressPercent} showInfo={false} size="small" strokeColor="#2ca7b4" />
            <div className="progress-text">{progressPercent}%</div>
          </Col>
        </Row>
      </div>
    </section>
  );
}
