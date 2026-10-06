import { Field, Section, h, type ConfiguratorUISpec } from "@gadgets/configurator-ui";
export default {
  initial: { selected: "brief" },
  isReady() { return true; },
  resourceUrl() { return "https://requirements.kotodama.invalid/current"; },
  render() {
    return <Section><Field label="Kotodamaの要件整理"
      description="閲覧を許可された依頼をCodexで処理します。任意のファイル操作や、メール・公開先への投稿は行いません。" /></Section>;
  },
} satisfies ConfiguratorUISpec<{}>;
