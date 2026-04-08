import { Button, Col, Form, Input, InputNumber, Modal, Row } from "antd";

export default function AdvancedModal({ open, onClose, formData, updateField }) {
  return (
    <Modal
      title="Advanced Options"
      open={open}
      onCancel={onClose}
      footer={<Button onClick={onClose}>Done</Button>}
      destroyOnHidden
    >
      <Form layout="vertical" requiredMark={false} style={{ marginTop: 8 }}>
        <Row gutter={[10, 0]}>
          <Col xs={24} md={12}>
            <Form.Item label="Fee Rate BPS">
              <Input value={formData.feeRateBps} onChange={(event) => updateField("feeRateBps", event.target.value)} />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item label="Missing Cost Warn Qty">
              <Input
                value={formData.missingCostWarnQty}
                onChange={(event) => updateField("missingCostWarnQty", event.target.value)}
              />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item label="Maker Reward Ratio">
              <Input value={formData.makerRewardRatio} onChange={(event) => updateField("makerRewardRatio", event.target.value)} />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item label="Concurrency">
              <Input value={formData.concurrency} onChange={(event) => updateField("concurrency", event.target.value)} />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item label="Page Limit">
              <Input value={formData.pageLimit} onChange={(event) => updateField("pageLimit", event.target.value)} />
            </Form.Item>
          </Col>
          <Col xs={24}>
            <Form.Item
              label="Peak notional axis cap (USDC)"
              extra="Session analytics: 0–cap split into 20 equal buckets for peak-position charts. Leave empty to use the max peak in your data."
            >
              <InputNumber
                min={0}
                step={10}
                placeholder="Empty = use data max"
                style={{ width: "100%", maxWidth: 280 }}
                value={formData.peakNotionalCapUsdc === "" ? undefined : Number(formData.peakNotionalCapUsdc)}
                onChange={(value) => updateField("peakNotionalCapUsdc", value === null || value === undefined ? "" : String(value))}
              />
            </Form.Item>
          </Col>
        </Row>
      </Form>
    </Modal>
  );
}
