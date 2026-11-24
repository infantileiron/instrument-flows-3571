CREATE TABLE IF NOT EXISTS reversal_lines (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    reversal_id BIGINT NOT NULL,
    original_id BIGINT NOT NULL,
    quantity INT NOT NULL CHECK (quantity > 0),
    FOREIGN KEY (reversal_id) REFERENCES receipts(id),
    FOREIGN KEY (original_id) REFERENCES receipts(id),
    INDEX line_reversal (reversal_id),
    INDEX line_original (original_id)
);
ALTER TABLE receipts
    MODIFY original_id BIGINT NULL,
    MODIFY source VARCHAR(12) NULL,
    MODIFY destination VARCHAR(12) NULL,
    MODIFY instrument VARCHAR(12) NULL,
    MODIFY quantity INT NULL,
    DROP CHECK receipts_chk_3,
    ADD CONSTRAINT receipts_kind_shape CHECK (
        (kind='loan' AND original_id IS NULL AND source IS NOT NULL AND destination IS NOT NULL
            AND instrument IS NOT NULL AND quantity IS NOT NULL)
        OR (kind='reversal' AND original_id IS NULL AND source IS NULL AND destination IS NULL
            AND instrument IS NULL AND quantity IS NULL));
INSERT INTO reversal_lines(reversal_id, original_id, quantity)
    SELECT id, original_id, quantity FROM receipts WHERE kind='reversal' AND original_id IS NOT NULL;
UPDATE receipts SET original_id=NULL, source=NULL, destination=NULL, instrument=NULL, quantity=NULL
    WHERE kind='reversal' AND original_id IS NOT NULL;
