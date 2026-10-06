package httpapi

import (
	"net/http"
	"strconv"
	"strings"

	"github.com/gofiber/fiber/v2"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
	"github.com/saimouli3/zippyy/apps/api/internal/ndr"
	"github.com/saimouli3/zippyy/apps/api/internal/platform"
	"github.com/saimouli3/zippyy/apps/api/internal/service"
	"github.com/saimouli3/zippyy/apps/api/internal/store"
)

func parseBody(c *fiber.Ctx, v any) error {
	if len(c.Body()) == 0 {
		return nil
	}
	if err := c.BodyParser(v); err != nil {
		return domain.NewError(http.StatusBadRequest, "INVALID_JSON", "request body is not valid JSON for this endpoint")
	}
	return nil
}

func sortKey(c *fiber.Ctx) domain.SortKey {
	switch strings.ToLower(c.Query("sort")) {
	case "eta":
		return domain.SortETA
	case "carrier":
		return domain.SortCarrier
	}
	return domain.SortPrice
}

// ---- orders ----

func (a *API) createOrder(c *fiber.Ctx) error {
	var in domain.CreateOrderInput
	if err := parseBody(c, &in); err != nil {
		return err
	}
	res, status, err := a.Svc.CreateOrder(c.UserContext(), in, c.Get("Idempotency-Key"))
	if err != nil {
		return err
	}
	return c.Status(status).JSON(res)
}

func (a *API) listOrders(c *fiber.Ctx) error {
	out, err := a.Svc.ListOrders(c.UserContext())
	if err != nil {
		return err
	}
	return c.JSON(fiber.Map{"orders": out})
}

func (a *API) getOrder(c *fiber.Ctx) error {
	o, err := a.Svc.GetOrder(c.UserContext(), c.Params("orderId"))
	if err != nil {
		return err
	}
	return c.JSON(o)
}

func (a *API) fetchRates(c *fiber.Ctx) error {
	refresh, _ := strconv.ParseBool(c.Query("refresh"))
	res, err := a.Svc.FetchRates(c.UserContext(), c.Params("orderId"), refresh, sortKey(c))
	if err != nil {
		return err
	}
	return c.JSON(res)
}

func (a *API) getRates(c *fiber.Ctx) error {
	res, err := a.Svc.GetRates(c.UserContext(), c.Params("orderId"), sortKey(c), nil, "")
	if err != nil {
		return err
	}
	return c.JSON(res)
}

func (a *API) selectCarrier(c *fiber.Ctx) error {
	var in service.SelectCarrierInput
	if err := parseBody(c, &in); err != nil {
		return err
	}
	res, err := a.Svc.SelectCarrier(c.UserContext(), c.Params("orderId"), in)
	if err != nil {
		return err
	}
	return c.JSON(res)
}

func (a *API) createShipment(c *fiber.Ctx) error {
	sh, created, err := a.Svc.CreateShipment(c.UserContext(), c.Params("orderId"))
	if err != nil {
		return err
	}
	status := http.StatusOK
	if created {
		status = http.StatusCreated
	}
	return c.Status(status).JSON(sh)
}

func (a *API) tracking(c *fiber.Ctx) error {
	res, err := a.Svc.GetTracking(c.UserContext(), c.Params("orderId"))
	if err != nil {
		return err
	}
	return c.JSON(res)
}

func (a *API) listShipments(c *fiber.Ctx) error {
	out, err := a.Svc.ListShipments(c.UserContext())
	if err != nil {
		return err
	}
	return c.JSON(fiber.Map{"shipments": out})
}

func (a *API) listCarriers(c *fiber.Ctx) error {
	type row struct {
		Code string `json:"code"`
		Name string `json:"name"`
	}
	var out []row
	for _, ad := range a.Svc.Registry.All() {
		out = append(out, row{ad.Code(), ad.Name()})
	}
	return c.JSON(fiber.Map{"carriers": out})
}

func (a *API) dashboard(c *fiber.Ctx) error {
	d, err := a.Store.R().Dashboard(c.UserContext())
	if err != nil {
		return err
	}
	return c.JSON(d)
}

// ---- webhooks ----

func (a *API) webhook(c *fiber.Ctx) error {
	res, err := a.Svc.HandleWebhook(c.UserContext(), c.Params("carrier"), append([]byte(nil), c.Body()...), c.Get("X-Carrier-Signature"))
	if err != nil {
		return err
	}
	return c.JSON(res)
}

func (a *API) webhookInbox(c *fiber.Ctx) error {
	out, err := a.Store.R().ListWebhookInbox(c.UserContext(), 100)
	if err != nil {
		return err
	}
	return c.JSON(fiber.Map{"entries": out})
}

// ---- NDR ----

func (a *API) listCases(c *fiber.Ctx) error {
	open, _ := strconv.ParseBool(c.Query("open"))
	out, err := a.NDR.ListCases(c.UserContext(), store.CaseFilter{State: c.Query("state"), Reason: c.Query("reason"), Carrier: c.Query("carrier"), OrderID: c.Query("orderId"), OpenOnly: open})
	if err != nil {
		return err
	}
	return c.JSON(fiber.Map{"cases": out})
}

func (a *API) getCase(c *fiber.Ctx) error {
	d, err := a.NDR.GetCase(c.UserContext(), c.Params("caseId"))
	if err != nil {
		return err
	}
	return c.JSON(d)
}

func (a *API) contactBuyer(c *fiber.Ctx) error {
	var in ndr.ContactOptions
	if err := parseBody(c, &in); err != nil {
		return err
	}
	res, err := a.NDR.Contact(c.UserContext(), c.Params("caseId"), in)
	if err != nil {
		return err
	}
	return c.JSON(res)
}

func (a *API) buyerReply(c *fiber.Ctx) error {
	var in struct {
		Text        string `json:"text"`
		Channel     string `json:"channel"`
		AutoProcess *bool  `json:"autoProcess"`
	}
	if err := parseBody(c, &in); err != nil {
		return err
	}
	auto := true
	if in.AutoProcess != nil {
		auto = *in.AutoProcess
	}
	res, err := a.NDR.BuyerReply(c.UserContext(), c.Params("caseId"), in.Text, strings.ToUpper(in.Channel), auto)
	if err != nil {
		return err
	}
	return c.JSON(res)
}

func (a *API) processCase(c *fiber.Ctx) error {
	var in struct {
		Trigger string `json:"trigger"`
	}
	if err := parseBody(c, &in); err != nil {
		return err
	}
	res, err := a.NDR.Process(c.UserContext(), c.Params("caseId"), strings.ToUpper(in.Trigger))
	if err != nil {
		return err
	}
	return c.JSON(res)
}

func (a *API) manualAction(c *fiber.Ctx) error {
	var in ndr.ManualActionInput
	if err := parseBody(c, &in); err != nil {
		return err
	}
	res, err := a.NDR.SubmitManualAction(c.UserContext(), c.Params("caseId"), in, platform.ActorFrom(c.UserContext()).Role)
	if err != nil {
		return err
	}
	return c.JSON(res)
}

func (a *API) caseTimeline(c *fiber.Ctx) error {
	out, err := a.NDR.Timeline(c.UserContext(), c.Params("caseId"))
	if err != nil {
		return err
	}
	return c.JSON(fiber.Map{"timeline": out})
}

// approveCase / rejectCase decide every pending blocking approval on the case that the caller's role may decide.
func (a *API) decideCase(c *fiber.Ctx, approve bool) error {
	var in struct {
		Note string `json:"note"`
	}
	if err := parseBody(c, &in); err != nil {
		return err
	}
	ctx := c.UserContext()
	role := platform.ActorFrom(ctx).Role
	if role == "" {
		return domain.Forbidden("a SELLER or OPS role is required to decide approvals")
	}
	list, err := a.NDR.ListApprovals(ctx, "PENDING", c.Params("caseId"))
	if err != nil {
		return err
	}
	var decided []store.Approval
	for _, ap := range list {
		mine := false
		for _, r := range ap.RequiredRoles {
			mine = mine || r == role
		}
		granted := false
		for _, r := range ap.GrantedRoles {
			granted = granted || r == role
		}
		if !mine || granted {
			continue
		}
		res, err := a.NDR.Decide(ctx, ap.ID, approve, in.Note)
		if err != nil {
			return err
		}
		decided = append(decided, *res)
	}
	if len(decided) == 0 {
		return domain.Conflict("NOTHING_TO_DECIDE", "no pending approval on this case can be decided by role "+role)
	}
	return c.JSON(fiber.Map{"approvals": decided})
}

func (a *API) approveCase(c *fiber.Ctx) error { return a.decideCase(c, true) }
func (a *API) rejectCase(c *fiber.Ctx) error  { return a.decideCase(c, false) }

// ---- approvals ----

func (a *API) listApprovals(c *fiber.Ctx) error {
	out, err := a.NDR.ListApprovals(c.UserContext(), strings.ToUpper(c.Query("status")), c.Query("caseId"))
	if err != nil {
		return err
	}
	return c.JSON(fiber.Map{"approvals": out})
}

func (a *API) decideOne(c *fiber.Ctx, approve bool) error {
	var in struct {
		Note string `json:"note"`
	}
	if err := parseBody(c, &in); err != nil {
		return err
	}
	res, err := a.NDR.Decide(c.UserContext(), c.Params("approvalId"), approve, in.Note)
	if err != nil {
		return err
	}
	return c.JSON(res)
}

func (a *API) approve(c *fiber.Ctx) error { return a.decideOne(c, true) }
func (a *API) reject(c *fiber.Ctx) error  { return a.decideOne(c, false) }

// ---- mock carrier control ----

func (a *API) trigger(c *fiber.Ctx) error {
	var in service.TriggerInput
	if err := parseBody(c, &in); err != nil {
		return err
	}
	out, err := a.Svc.TriggerEvent(c.UserContext(), c.Params("carrier"), c.Params("shipmentId"), in)
	if err != nil {
		return err
	}
	c.Set("Content-Type", "application/json")
	return c.Send(out)
}

func (a *API) faults(c *fiber.Ctx) error {
	var in struct {
		Fault         string `json:"fault"`
		RejectActions *bool  `json:"rejectActions"`
	}
	if err := parseBody(c, &in); err != nil {
		return err
	}
	out, err := a.Svc.MockFaultConfig(c.UserContext(), c.Params("carrier"), in.Fault, in.RejectActions)
	if err != nil {
		return err
	}
	c.Set("Content-Type", "application/json")
	return c.Send(out)
}

func (a *API) mockStats(c *fiber.Ctx) error {
	out, err := a.Svc.MockStats(c.UserContext(), c.Params("carrier"))
	if err != nil {
		return err
	}
	c.Set("Content-Type", "application/json")
	return c.Send(out)
}

// ---- rules ----

func (a *API) listSellerRules(c *fiber.Ctx) error {
	out, err := a.Store.R().ListSellerRules(c.UserContext())
	if err != nil {
		return err
	}
	return c.JSON(fiber.Map{"rules": out})
}

func (a *API) putSellerRules(c *fiber.Ctx) error {
	if platform.ActorFrom(c.UserContext()).Role != domain.RoleSeller {
		return domain.Forbidden("only the SELLER role may change seller rules")
	}
	var in domain.SellerRules
	if err := parseBody(c, &in); err != nil {
		return err
	}
	in.MerchantID = c.Params("merchantId")
	if in.MaxAttempts < 1 || in.MaxAttempts > 10 {
		return domain.Validation("invalid seller rules", map[string]string{"maxAttempts": "must be between 1 and 10"})
	}
	if in.AutoRTOAttempt < 0 || in.AutoRTOAttempt > 10 {
		return domain.Validation("invalid seller rules", map[string]string{"autoRtoAttempt": "must be between 0 and 10"})
	}
	switch in.EarlyRTOPolicy {
	case "AUTO", "APPROVAL", "DISALLOWED":
	default:
		return domain.Validation("invalid seller rules", map[string]string{"earlyRtoPolicy": "must be AUTO, APPROVAL or DISALLOWED"})
	}
	if in.DefaultOnSilence != "RTO" && in.DefaultOnSilence != "ESCALATE" {
		return domain.Validation("invalid seller rules", map[string]string{"defaultOnSilence": "must be RTO or ESCALATE"})
	}
	if len(in.AllowedChannels) == 0 {
		return domain.Validation("invalid seller rules", map[string]string{"allowedChannels": "at least one channel is required"})
	}
	for _, ch := range in.AllowedChannels {
		if ch != "WHATSAPP" && ch != "IVR" && ch != "SMS" {
			return domain.Validation("invalid seller rules", map[string]string{"allowedChannels": "unknown channel " + ch})
		}
	}
	for _, act := range in.AllowedActions {
		if !domain.ActionType(act).Valid() {
			return domain.Validation("invalid seller rules", map[string]string{"allowedActions": "unknown action " + act})
		}
	}
	if in.CommHoursStart == "" {
		in.CommHoursStart = "08:00"
	}
	if in.CommHoursEnd == "" {
		in.CommHoursEnd = "21:00"
	}
	if in.BuyerResponseTimeoutMinutes <= 0 {
		in.BuyerResponseTimeoutMinutes = 240
	}
	if in.SellerResponseTimeoutMinutes <= 0 {
		in.SellerResponseTimeoutMinutes = 720
	}
	if err := a.Store.R().UpsertSellerRules(c.UserContext(), in); err != nil {
		return err
	}
	_ = a.Store.R().InsertAudit(c.UserContext(), store.AuditEntry{Actor: platform.ActorFrom(c.UserContext()).Name, ActorType: domain.ActorSeller, Action: "SELLER_RULES_UPDATED", Evidence: in, RequestID: platform.RequestID(c.UserContext())})
	out, err := a.Store.R().GetSellerRules(c.UserContext(), in.MerchantID)
	if err != nil {
		return err
	}
	return c.JSON(out)
}

func (a *API) listCarrierRules(c *fiber.Ctx) error {
	out, err := a.Store.R().ListCarrierRules(c.UserContext())
	if err != nil {
		return err
	}
	return c.JSON(fiber.Map{"rules": out})
}

func (a *API) putCarrierRules(c *fiber.Ctx) error {
	if platform.ActorFrom(c.UserContext()).Role != domain.RoleOps {
		return domain.Forbidden("only the OPS role may change carrier constraints")
	}
	var in domain.CarrierRules
	if err := parseBody(c, &in); err != nil {
		return err
	}
	in.CarrierCode = strings.ToUpper(c.Params("code"))
	if _, ok := a.Svc.Registry.Get(in.CarrierCode); !ok {
		return domain.Validation("unknown carrier", map[string]string{"code": in.CarrierCode})
	}
	if in.MaxAttempts < 1 || in.HoldWindowDays < 1 {
		return domain.Validation("invalid carrier rules", map[string]string{"maxAttempts": "must be >= 1", "holdWindowDays": "must be >= 1"})
	}
	if len(in.InstructionCutoff) != 5 || in.InstructionCutoff[2] != ':' {
		return domain.Validation("invalid carrier rules", map[string]string{"instructionCutoff": "must be HH:MM"})
	}
	for _, act := range in.SupportedActions {
		if !domain.ActionType(act).Valid() {
			return domain.Validation("invalid carrier rules", map[string]string{"supportedActions": "unknown action " + act})
		}
	}
	if err := a.Store.R().UpsertCarrierRules(c.UserContext(), in); err != nil {
		return err
	}
	_ = a.Store.R().InsertAudit(c.UserContext(), store.AuditEntry{Actor: platform.ActorFrom(c.UserContext()).Name, ActorType: domain.ActorOps, Action: "CARRIER_RULES_UPDATED", Evidence: in, RequestID: platform.RequestID(c.UserContext())})
	out, err := a.Store.R().GetCarrierRules(c.UserContext(), in.CarrierCode)
	if err != nil {
		return err
	}
	return c.JSON(out)
}

func (a *API) auditLogs(c *fiber.Ctx) error {
	limit, _ := strconv.Atoi(c.Query("limit"))
	f := store.AuditFilter{ActorType: strings.ToUpper(c.Query("actorType")), Action: c.Query("action"), Limit: limit}
	if oid := c.Query("orderId"); oid != "" {
		o, err := a.Svc.GetOrder(c.UserContext(), oid)
		if err != nil {
			return err
		}
		f.OrderID = o.ID
	}
	if cid := c.Query("caseId"); cid != "" {
		cs, err := a.NDR.GetCase(c.UserContext(), cid)
		if err != nil {
			return err
		}
		f.CaseID = cs.Case.ID
	}
	out, err := a.Store.R().ListAudit(c.UserContext(), f)
	if err != nil {
		return err
	}
	return c.JSON(fiber.Map{"logs": out})
}
