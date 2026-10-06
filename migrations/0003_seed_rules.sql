-- Reference data: default seller rules for the demo merchant and per-carrier constraints.
INSERT INTO seller_rules (merchant_id) VALUES ('MRC-100') ON CONFLICT DO NOTHING;

INSERT INTO carrier_rules (carrier_code, max_attempts, instruction_cutoff, hold_window_days, supported_actions,
                           supports_time_slot, can_change_payment_mode, can_change_address, can_change_phone)
VALUES
 ('FASTSHIP',     3, '23:59', 7, '{REQUEST_REATTEMPT,RESCHEDULE,UPDATE_PHONE,UPDATE_ADDRESS,CONVERT_TO_PREPAID,INITIATE_RTO}', TRUE,  TRUE,  TRUE,  TRUE),
 ('QUICKEXPRESS', 3, '22:00', 5, '{REQUEST_REATTEMPT,RESCHEDULE,UPDATE_PHONE,UPDATE_ADDRESS,INITIATE_RTO}',                    TRUE,  FALSE, TRUE,  TRUE),
 ('RELIABLE',     2, '20:00', 4, '{REQUEST_REATTEMPT,RESCHEDULE,UPDATE_PHONE,CONVERT_TO_PREPAID,INITIATE_RTO}',                 FALSE, TRUE,  FALSE, TRUE)
ON CONFLICT DO NOTHING;
