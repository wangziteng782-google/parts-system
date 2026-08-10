let currentProductId = null;
        let currentData = null;
        let currentVariantSpecs = [];
        let currentVariantPrices = [];
        let currentVariantCombinations = [];
        let selectedVariantValues = [];
        let currentSelectedVariantPrice = null;
        let searchTimer = null;
        let currentPage = 1;
        let totalRecords = 0;
        const PAGE_SIZE = 30;
        let fieldLabels = {};
        let imgLibFieldLabels = {}; // 图片库字段标签
        let classificationTree = [];
        let productTypeValues = [];
        let productTypeCounts = {};
        let unclassifiedProductCount = 0;
        let correctionProductCount = 0;
        let selectedProductType = '';
        let showUnclassified = false;
        let showCorrection = false;
        let showDuplicatesOnly = false;
        let currentProductFeedback = [];
        let currentProductFeedbackHistory = [];
        let imageUploadConfig = { configured: false };
        let localImageTargetField = null;
        let localImageUploading = false;
        let pendingCreateLocalFiles = {};
        let pendingCreateLibraryUrls = {};
        const createImagePreviewUrls = new WeakMap();
        let createLocalImageTargetField = null;
        let imgLibCreateMode = false;

        const IMAGE_FIELDS = ['key_part_images', 'actual_photos', 'product_image_3', 'product_image_4',
            'product_image_5', 'product_image_6', 'product_image_7', 'product_image_8',
            'product_image_9', 'product_image_10', 'product_detail_images'];
        const CREATE_PRODUCT_IMAGE_FIELDS = [
            'key_part_images',
            'actual_photos',
            'product_detail_images',
        ];

        const PRODUCT_CREATE_SECTIONS = [
            {
                title: '产品基本信息',
                fields: [
                    ['product_name', '产品名称', 'text'],
                    ['model', '型号', 'text'],
                    ['product_brand', '产品品牌', 'text'],
                    ['product_type', '产品分类', 'product_type'],
                    ['applicable_elevator_brand', '适用电梯品牌', 'text'],
                    ['substitute_model', '替代型号', 'text'],
                ],
            },
            {
                title: '参数与说明',
                fields: [
                    ['technical_params', '技术参数', 'textarea'],
                    ['precautions', '注意事项', 'textarea'],
                    ['remark', '备注', 'textarea'],
                    ['remark_2', '备注(2)', 'textarea'],
                ],
            },
            {
                title: '主表价格信息',
                fields: [
                    ['purchase_cost', '采购成本价', 'text'],
                    ['purchase_special_invoice', '进项专票', 'text'],
                    ['purchase_general_invoice', '进项普票', 'text'],
                    ['purchase_shipping', '采购运费', 'text'],
                ],
            },
        ];
