// Package httpapi is the Fiber HTTP layer: routing, middleware, request/response mapping. It contains no
// business logic; handlers call the service and ndr packages.
package httpapi

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/gofiber/fiber/v2/middleware/cors"
	"github.com/gofiber/fiber/v2/middleware/recover"
	"github.com/google/uuid"

	"github.com/saimouli3/zippyy/apps/api/internal/domain"
	"github.com/saimouli3/zippyy/apps/api/internal/ndr"
	"github.com/saimouli3/zippyy/apps/api/internal/platform"
	"github.com/saimouli3/zippyy/apps/api/internal/service"
	"github.com/saimouli3/zippyy/apps/api/internal/store"
	"github.com/saimouli3/zippyy/docs"
)

type API struct {
	Svc     *service.Services
	NDR     *ndr.Service
	Store   *store.Store
	Log     *slog.Logger
	Metrics *platform.Metrics
	Origins string
	Ready   func(ctx context.Context) error
}

func (a *API) App() *fiber.App {
	app := fiber.New(fiber.Config{
		DisableStartupMessage: true,
		BodyLimit:             1 << 20,
		ReadTimeout:           15 * time.Second,
		WriteTimeout:          60 * time.Second,
		ErrorHandler:          a.errorHandler,
	})
	app.Use(recover.New())
	origins := a.Origins
	if origins == "" {
		origins = "*"
	}
	app.Use(cors.New(cors.Config{AllowOrigins: origins, AllowHeaders: "Content-Type, Idempotency-Key, X-Request-ID, X-Correlation-ID, X-Zippy-Role, X-Zippy-Actor", ExposeHeaders: "X-Request-ID"}))
	app.Use(a.requestContext)

	app.Get("/health", func(c *fiber.Ctx) error { return c.JSON(fiber.Map{"status": "ok"}) })
	app.Get("/ready", func(c *fiber.Ctx) error {
		if a.Ready != nil {
			if err := a.Ready(c.UserContext()); err != nil {
				return c.Status(503).JSON(fiber.Map{"status": "unavailable", "error": err.Error()})
			}
		}
		return c.JSON(fiber.Map{"status": "ready"})
	})

	api := app.Group("/api")
	api.Get("/openapi.yaml", func(c *fiber.Ctx) error {
		c.Set("Content-Type", "application/yaml")
		return c.Send(docs.OpenAPI)
	})
	api.Get("/docs", func(c *fiber.Ctx) error {
		c.Set("Content-Type", "text/html; charset=utf-8")
		return c.SendString(swaggerHTML)
	})
	api.Get("/metrics", func(c *fiber.Ctx) error { return c.JSON(a.Metrics.Snapshot()) })
	api.Get("/carriers", a.listCarriers)
	api.Get("/dashboard", a.dashboard)

	// orders & logistics
	api.Post("/orders", a.createOrder)
	api.Get("/orders", a.listOrders)
	api.Get("/orders/:orderId", a.getOrder)
	api.Post("/orders/:orderId/rates", a.fetchRates)
	api.Get("/orders/:orderId/rates", a.getRates)
	api.Post("/orders/:orderId/select-carrier", a.selectCarrier)
	api.Post("/orders/:orderId/shipment", a.createShipment)
	api.Get("/orders/:orderId/tracking", a.tracking)
	api.Get("/shipments", a.listShipments)

	// carrier webhooks (carrier-specific endpoints share one hardened pipeline)
	api.Post("/webhooks/:carrier", a.webhook)
	api.Get("/webhooks-inbox", a.webhookInbox)

	// NDR
	api.Get("/ndr/cases", a.listCases)
	api.Get("/ndr/cases/:caseId", a.getCase)
	api.Post("/ndr/cases/:caseId/contact", a.contactBuyer)
	api.Post("/ndr/cases/:caseId/buyer-reply", a.buyerReply)
	api.Post("/ndr/cases/:caseId/process", a.processCase)
	api.Post("/ndr/cases/:caseId/approve", a.approveCase)
	api.Post("/ndr/cases/:caseId/reject", a.rejectCase)
	api.Post("/ndr/cases/:caseId/actions", a.manualAction)
	api.Get("/ndr/cases/:caseId/timeline", a.caseTimeline)

	// approvals
	api.Get("/approvals", a.listApprovals)
	api.Post("/approvals/:approvalId/approve", a.approve)
	api.Post("/approvals/:approvalId/reject", a.reject)

	// mock carrier control
	api.Post("/mock-carriers/:carrier/shipments/:shipmentId/trigger", a.trigger)
	api.Post("/mock-carriers/:carrier/faults", a.faults)
	api.Get("/mock-carriers/:carrier/stats", a.mockStats)

	// rules
	api.Get("/rules/seller", a.listSellerRules)
	api.Put("/rules/seller/:merchantId", a.putSellerRules)
	api.Get("/rules/carriers", a.listCarrierRules)
	api.Put("/rules/carriers/:code", a.putCarrierRules)

	api.Get("/audit-logs", a.auditLogs)
	return app
}

// requestContext assigns request/correlation ids, a request-scoped logger and the acting identity.
func (a *API) requestContext(c *fiber.Ctx) error {
	start := time.Now()
	rid := c.Get("X-Request-ID")
	if rid == "" {
		rid = uuid.NewString()
	}
	cid := c.Get("X-Correlation-ID")
	if cid == "" {
		cid = rid
	}
	c.Set("X-Request-ID", rid)
	c.Set("X-Correlation-ID", cid)
	logger := a.Log.With("requestId", rid, "correlationId", cid)
	ctx := platform.WithLogger(c.UserContext(), logger)
	ctx = platform.WithRequestID(ctx, rid)
	role := strings.ToUpper(strings.TrimSpace(c.Get("X-Zippy-Role")))
	if role != domain.RoleSeller && role != domain.RoleOps {
		role = ""
	}
	name := strings.TrimSpace(c.Get("X-Zippy-Actor"))
	if len(name) > 64 {
		name = name[:64]
	}
	if name == "" && role != "" {
		name = strings.ToLower(role) + "-user"
	}
	ctx = platform.WithActor(ctx, platform.Actor{Name: name, Role: role})
	c.SetUserContext(ctx)
	c.Locals("requestId", rid)
	err := c.Next()
	logger.Info("request", "event", "HTTP_REQUEST", "method", c.Method(), "path", c.Path(), "status", c.Response().StatusCode(), "durationMs", time.Since(start).Milliseconds())
	return err
}

func (a *API) errorHandler(c *fiber.Ctx, err error) error {
	rid, _ := c.Locals("requestId").(string)
	ae, ok := domain.AsAppError(err)
	if !ok {
		var fe *fiber.Error
		if errors.As(err, &fe) {
			ae = domain.NewError(fe.Code, strings.ToUpper(strings.ReplaceAll(http.StatusText(fe.Code), " ", "_")), fe.Message)
		} else if errors.Is(err, store.ErrNotFound) {
			ae = domain.NotFound("resource")
		} else {
			platform.L(c.UserContext()).Error("unhandled error", "event", "UNHANDLED_ERROR", "error", err.Error())
			ae = domain.NewError(http.StatusInternalServerError, "INTERNAL_ERROR", "an unexpected error occurred")
		}
	}
	body := fiber.Map{"code": ae.Code, "message": ae.Message, "requestId": rid}
	if ae.Details != nil {
		body["details"] = ae.Details
	}
	return c.Status(ae.Status).JSON(fiber.Map{"error": body})
}

const swaggerHTML = `<!doctype html><html><head><meta charset="utf-8"><title>Zippyy API</title>
<link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css"></head>
<body><div id="ui"></div><script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>SwaggerUIBundle({url:'/api/openapi.yaml',dom_id:'#ui'})</script></body></html>`
