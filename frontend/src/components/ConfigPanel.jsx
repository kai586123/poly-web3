import { Button, Col, Dropdown, Form, Input, Row } from "antd";
import { DownloadOutlined } from "@ant-design/icons";

export default function ConfigPanel({
  formData,
  updateField,
  downloads,
  onOpenAdvanced,
  onToggleRun,
  onReset,
  running,
  runStatus,
}) {
  const exportItems = [
    {
      key: "json",
      disabled: !downloads,
      label: downloads ? (
        <a href={downloads.json} target="_blank" rel="noreferrer">
          JSON
        </a>
      ) : (
        "JSON"
      ),
    },
    {
      key: "total",
      disabled: !downloads,
      label: downloads ? (
        <a href={downloads.total_curve_csv} target="_blank" rel="noreferrer">
          Total CSV
        </a>
      ) : (
        "Total CSV"
      ),
    },
    {
      key: "market",
      disabled: !downloads,
      label: downloads ? (
        <a href={downloads.market_curve_csv} target="_blank" rel="noreferrer">
          Market CSV
        </a>
      ) : (
        "Market CSV"
      ),
    },
  ];

  return (
    <section className="config-card">
      <Form layout="vertical" requiredMark={false} className="config-form">
        <Row gutter={[10, 4]} align="bottom">
          <Col xs={24} lg={11}>
            <Form.Item label="Address">
              <Input value={formData.address} onChange={(event) => updateField("address", event.target.value)} />
            </Form.Item>
          </Col>
          <Col xs={24} md={12} lg={7}>
            <Form.Item label="Symbols">
              <Input value={formData.symbols} onChange={(event) => updateField("symbols", event.target.value)} />
            </Form.Item>
          </Col>
          <Col xs={12} md={6} lg={4}>
            <Form.Item label="Intervals">
              <Input value={formData.intervals} onChange={(event) => updateField("intervals", event.target.value)} />
            </Form.Item>
          </Col>
          <Col xs={12} md={6} lg={2}>
            <Form.Item label=" ">
              <Dropdown menu={{ items: exportItems }} trigger={["click"]}>
                <Button icon={<DownloadOutlined />} style={{ width: "100%" }}>
                  Export
                </Button>
              </Dropdown>
            </Form.Item>
          </Col>
        </Row>

        <Row gutter={[10, 4]} align="bottom">
          <Col xs={24} lg={16}>
            <Form.Item label="Time Window">
              <div className="time-row">
                <Input value={formData.startTime} onChange={(event) => updateField("startTime", event.target.value)} placeholder="YYYY-MM-DD HH:MM" />
                <span className="time-separator">--</span>
                <Input value={formData.endTime} onChange={(event) => updateField("endTime", event.target.value)} placeholder="YYYY-MM-DD HH:MM" />
              </div>
            </Form.Item>
          </Col>

          <Col xs={24} lg={8}>
            <div className="action-row">
              <Button onClick={onOpenAdvanced}>Advanced</Button>
              <Button
                type="primary"
                onClick={onToggleRun}
                disabled={runStatus === "STOPPING"}
                danger={running}
                className="session-btn"
              >
                {running ? "Stop Session" : "Start Session"}
              </Button>
              <Button onClick={onReset}>Reset</Button>
            </div>
          </Col>
        </Row>
      </Form>
    </section>
  );
}
