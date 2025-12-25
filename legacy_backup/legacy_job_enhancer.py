# job_enhancer.py
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional
import csv

from PIL import Image
from tqdm import tqdm

from print_enhancer import enhance_one, save_with_metadata, EnhanceConfig


@dataclass
class ImageJob:
    imageId: str
    pageNo: int
    print_inches_short_side: float
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ImageJob':
        return cls(**data)


@dataclass
class JobResult:
    imageId: str
    pageNo: int
    success: bool
    output_path: Optional[str] = None
    error_message: Optional[str] = None
    enhancement_metadata: Optional[Dict[str, Any]] = None


class JobEnhancer:
    def __init__(self, base_config: Optional[EnhanceConfig] = None):
        self.base_config = base_config or EnhanceConfig()
    
    def load_jobs_from_file(self, jobs_file: str | Path) -> List[ImageJob]:
        """Load jobs from a JSON file."""
        with open(jobs_file, 'r') as f:
            jobs_data = json.load(f)
        return [ImageJob.from_dict(job) for job in jobs_data]
    
    def load_jobs_from_data(self, jobs_data: List[Dict[str, Any]]) -> List[ImageJob]:
        """Load jobs from a list of dictionaries."""
        return [ImageJob.from_dict(job) for job in jobs_data]
    
    def enhance_job(
        self, 
        job: ImageJob, 
        input_image_path: str | Path,
        output_dir: str | Path
    ) -> JobResult:
        """
        Enhance a single image based on the job configuration.
        
        Args:
            job: ImageJob configuration
            input_image_path: Path to the source image
            output_dir: Directory where enhanced image will be saved
        
        Returns:
            JobResult with success status and metadata
        """
        try:
            input_path = Path(input_image_path)
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Create custom config for this job
            job_config = EnhanceConfig(
                **{**asdict(self.base_config), 'print_inches_short_side': job.print_inches_short_side}
            )
            
            # Process the image
            with Image.open(input_path) as pil_img:
                icc_profile = pil_img.info.get("icc_profile", None)
                enhanced_img, chosen_dpi, metadata = enhance_one(pil_img, icc_profile, job_config)
                
                # Generate output filename
                output_filename = f"{job.imageId}_page{job.pageNo:02d}.jpg"
                output_path = output_dir / output_filename
                
                # Save enhanced image
                save_with_metadata(enhanced_img, output_path, chosen_dpi, job_config, icc_profile)
                
                # Add job-specific metadata
                metadata.update({
                    'imageId': job.imageId,
                    'pageNo': job.pageNo,
                    'requested_print_size': job.print_inches_short_side,
                    'output_filename': output_filename
                })
                
                return JobResult(
                    imageId=job.imageId,
                    pageNo=job.pageNo,
                    success=True,
                    output_path=str(output_path),
                    enhancement_metadata=metadata
                )
                
        except Exception as e:
            return JobResult(
                imageId=job.imageId,
                pageNo=job.pageNo,
                success=False,
                error_message=str(e)
            )
    
    def enhance_jobs_batch(
        self,
        jobs: List[ImageJob],
        input_images_dir: str | Path,
        output_dir: str | Path,
        image_extension: str = ".jpg"
    ) -> List[JobResult]:
        """
        Process a batch of image enhancement jobs.
        
        Args:
            jobs: List of ImageJob configurations
            input_images_dir: Directory containing source images (named by imageId)
            output_dir: Directory where enhanced images will be saved
            image_extension: Extension to look for in input images
        
        Returns:
            List of JobResult objects
        """
        input_dir = Path(input_images_dir)
        results = []
        
        for job in tqdm(jobs, desc="Processing image jobs"):
            # Look for input image by imageId
            input_image_path = input_dir / f"{job.imageId}{image_extension}"
            
            if not input_image_path.exists():
                # Try common extensions if specified extension doesn't exist
                for ext in ['.jpg', '.jpeg', '.png']:
                    alt_path = input_dir / f"{job.imageId}{ext}"
                    if alt_path.exists():
                        input_image_path = alt_path
                        break
                else:
                    # No image found
                    results.append(JobResult(
                        imageId=job.imageId,
                        pageNo=job.pageNo,
                        success=False,
                        error_message=f"Image file not found: {job.imageId}"
                    ))
                    continue
            
            result = self.enhance_job(job, input_image_path, output_dir)
            results.append(result)
        
        return results
    
    def save_results_report(self, results: List[JobResult], report_path: str | Path) -> None:
        """Save processing results to a CSV report."""
        report_path = Path(report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        
        rows = []
        for result in results:
            row = {
                'imageId': result.imageId,
                'pageNo': result.pageNo,
                'success': result.success,
                'output_path': result.output_path or '',
                'error_message': result.error_message or ''
            }
            
            # Add enhancement metadata if available
            if result.enhancement_metadata:
                row.update({
                    'src_w': result.enhancement_metadata.get('src_w', ''),
                    'src_h': result.enhancement_metadata.get('src_h', ''),
                    'dst_w': result.enhancement_metadata.get('dst_w', ''),
                    'dst_h': result.enhancement_metadata.get('dst_h', ''),
                    'chosen_dpi': result.enhancement_metadata.get('chosen_dpi', ''),
                    'did_upscale': result.enhancement_metadata.get('did_upscale', ''),
                    'scale_factor': result.enhancement_metadata.get('scale_for_chosen', ''),
                    'sharpen_amount': result.enhancement_metadata.get('sharpen_amount', ''),
                    'requested_print_size': result.enhancement_metadata.get('requested_print_size', ''),
                    'dpi_reason': result.enhancement_metadata.get('dpi_reason', '')
                })
            
            rows.append(row)
        
        if rows:
            with open(report_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)


def enhance_from_jobs_file(
    jobs_file: str | Path,
    input_images_dir: str | Path,
    output_dir: str | Path,
    base_config: Optional[EnhanceConfig] = None
) -> tuple[List[JobResult], Path]:
    """
    Convenience function to enhance images from a jobs file.
    
    Returns:
        Tuple of (results, report_path)
    """
    enhancer = JobEnhancer(base_config)
    jobs = enhancer.load_jobs_from_file(jobs_file)
    results = enhancer.enhance_jobs_batch(jobs, input_images_dir, output_dir)
    
    report_path = Path(output_dir) / "job_enhancement_report.csv"
    enhancer.save_results_report(results, report_path)
    
    return results, report_path


def enhance_from_jobs_data(
    jobs_data: List[Dict[str, Any]],
    input_images_dir: str | Path,
    output_dir: str | Path,
    base_config: Optional[EnhanceConfig] = None
) -> tuple[List[JobResult], Path]:
    """
    Convenience function to enhance images from jobs data.
    
    Returns:
        Tuple of (results, report_path)
    """
    enhancer = JobEnhancer(base_config)
    jobs = enhancer.load_jobs_from_data(jobs_data)
    results = enhancer.enhance_jobs_batch(jobs, input_images_dir, output_dir)
    
    report_path = Path(output_dir) / "job_enhancement_report.csv"
    enhancer.save_results_report(results, report_path)
    
    return results, report_path